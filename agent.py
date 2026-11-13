"""One model call: OpenAI-compatible chat API, disk cache, retry and stop rules.

Copied and adapted from swarm-failure-lab/agent.py (transport, cache, retry rules).
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
MAX_RETRIES = 6
MAX_WAIT_S = 120  # a longer retry-after usually means a daily cap: stop instead of sleeping
DEFAULT_ENDPOINT = "https://api.groq.com/openai/v1"  # Groq: uses GROQ_API_KEY
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai"  # uses LLM_API_KEY
DEFAULT_MODEL = "gemini-3.8-flash"  # D21; the qwen and gpt-oss runs passed --model/--endpoint
ENDPOINT = DEFAULT_ENDPOINT  # one endpoint per process, set by --endpoint via set_endpoint()

_client = None


class CallFailed(Exception):
    """A model call failed with a non-retryable API error (e.g. 400, 401, 404)."""
    def __init__(self, message, retries):
        super().__init__(message)
        self.retries = retries


class RateLimitStop(Exception):
    """Rate limits or connection errors outlasted the backoff. The run must stop and be resumed."""


class RequestTooLarge(Exception):
    """The prompt exceeds the provider's per-request token limit. Retrying cannot help.

    requested_tokens and limit_tokens are parsed from the provider message when present."""
    def __init__(self, message):
        super().__init__(message)
        m = re.search(r"Limit\s+(\d+),\s*Requested\s+(\d+)", message or "")
        self.limit_tokens = int(m.group(1)) if m else None
        self.requested_tokens = int(m.group(2)) if m else None
        low = (message or "").lower()
        # D15: "input" = the prompt itself is over the limit (did not fit); "output" = the
        # provider's expected output for this request is over the per-minute output limit.
        self.limit_kind = ("output" if "output tokens" in low else
                           "input" if "input tokens" in low else
                           "combined" if "tokens per minute" in low else      # D24: Groq TPM
                           "input" if "413" in low else None)


class Pacer:
    """Client-side sliding windows for input and output tokens per minute (D10, D12).

    Input: before a live call, waits until (input tokens sent in the last 60 s + this call's
    estimate) fits under `itpm`. A call whose estimate alone exceeds `itpm` is sent anyway: the
    provider rejects it (RequestTooLarge) without spending budget.
    Output: waits until (output tokens counted in the last 60 s + out_reserve) fits under `otpm`.
    Each call counts as max(its completion tokens, out_reserve), because the provider may count
    the full max_tokens (D15). A 429 with a short retry-after covers the rest.
    A limit of 0 disables that window.
    """
    CHARS_PER_TOKEN = 1.2  # measured 1.33 on a size-S prompt (D9); digits tokenise one by one

    def __init__(self, itpm=7000, otpm=0, out_reserve=300, window_s=60.0, clock=time.monotonic,
                 sleep=None, combined=False):
        self.itpm, self.otpm, self.window_s, self.clock = itpm, otpm, window_s, clock
        self.out_reserve = out_reserve
        # combined=True (D24, Groq gpt-oss): `itpm` is one tokens-per-minute limit counting input
        # plus requested max_tokens before the call, and input plus actual output after it.
        self.combined = combined
        self.sleep = sleep or (lambda s: time.sleep(s))
        self.sent = []  # (timestamp, input tokens, output tokens)

    def estimate(self, messages):
        return int(sum(len(m["content"]) for m in messages) / self.CHARS_PER_TOKEN) + 20

    def _used(self, now):
        self.sent = [e for e in self.sent if now - e[0] < self.window_s]
        return sum(e[1] for e in self.sent), sum(e[2] for e in self.sent)

    def _blocked(self, tokens):
        used_in, used_out = self._used(self.clock())
        over_in = bool(self.itpm) and tokens <= self.itpm and used_in + tokens > self.itpm
        over_out = bool(self.otpm) and used_out + min(self.out_reserve, self.otpm) > self.otpm
        return over_in or over_out

    def wait_for(self, tokens):
        waited = 0.0
        while self._blocked(tokens):
            pause = max(self.sent[0][0] + self.window_s - self.clock() + 0.5, 0.5)
            self.sleep(pause)
            waited += pause
        return waited

    def record(self, tokens, out_tokens=0):
        self.sent.append((self.clock(), tokens,
                          max(out_tokens, self.out_reserve if self.otpm else 0)))


PACER = Pacer(itpm=0)  # the CLI sets the real limits (--itpm, --otpm); tests stay unpaced


def set_endpoint(url):
    """Point every call in this process at an OpenAI-compatible API (the --endpoint flag)."""
    global ENDPOINT, _client
    ENDPOINT, _client = url.rstrip("/"), None


def cache_key(model, temperature, reasoning_effort, messages, call_id, max_tokens=None):
    """call_id = [task_id, role, index]: identical prompts in different roles never share a response."""
    # float(): 0 and 0.0 must share a key (D15: the CLI passes 0.0)
    payload = json.dumps([model, float(temperature), reasoning_effort, max_tokens, messages, call_id,
                          ENDPOINT])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def client():
    global _client
    if _client is None:
        import httpx
        import truststore
        from dotenv import load_dotenv
        truststore.inject_into_ssl()  # OS certificate store; verification stays on
        load_dotenv(Path(__file__).parent / ".env")
        key = os.environ.get("GROQ_API_KEY" if ENDPOINT == DEFAULT_ENDPOINT else "LLM_API_KEY")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        _client = httpx.Client(base_url=ENDPOINT, headers=headers, timeout=600)  # D21: Gemini L calls take ~4 min
    return _client


def _too_large(status, text):
    return status == 413 or "request too large" in (text or "").lower()


def call_model(model, temperature, reasoning_effort, messages, post=None, max_tokens=None):
    """One POST to {ENDPOINT}/chat/completions. Fresh context: only `messages`, no history.

    Retries only when no model response arrived: 429, 5xx, connection error, timeout.
    `post` is injectable for tests; it takes the JSON body and returns an httpx-like response.
    """
    import httpx

    post = post or (lambda body: client().post("/chat/completions", json=body))
    body = {"model": model, "temperature": temperature, "messages": messages}
    if reasoning_effort is not None:
        body["reasoning_effort"] = reasoning_effort
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    for attempt in range(MAX_RETRIES + 1):
        BUDGET.take(model)  # D23: every HTTP attempt counts against the provider's daily quota
        start = time.perf_counter()
        try:
            resp = post(body)
        except httpx.TransportError as e:
            resp, error = None, f"{type(e).__name__}: {e}"
        else:
            error = f"HTTP {resp.status_code}: {resp.text[:400]}"
            if resp.status_code == 200:
                data = resp.json()
                choice, usage = data["choices"][0], data.get("usage") or {}
                message = choice["message"]
                limits = {k.lower(): v for k, v in (getattr(resp, "headers", None) or {}).items()
                          if k.lower().startswith("x-ratelimit")}
                return {
                    "finish_reason": choice.get("finish_reason"),
                    "ratelimit_headers": limits,
                    "raw_text": message.get("content"),
                    "reasoning": message.get("reasoning"),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "usage": usage,  # provider's full usage block (e.g. hidden reasoning counts)
                    "latency_ms": round((time.perf_counter() - start) * 1000),
                    "retries": attempt,
                }
            if _too_large(resp.status_code, resp.text):
                raise RequestTooLarge(error)
            if resp.status_code != 429 and resp.status_code < 500:
                raise CallFailed(error, attempt)
        wait = 2 ** attempt
        if resp is not None and resp.status_code == 429:
            if _daily_quota(resp.text):  # D23: retrying cannot help and each retry costs quota
                raise RateLimitStop(f"daily quota exhausted: {_quota_summary(resp.text)}")
            wait = float(resp.headers.get("retry-after") or _retry_delay(resp.text) or wait)
        if attempt == MAX_RETRIES or wait > MAX_WAIT_S:
            raise RateLimitStop(f"{error} after {attempt} retries (next wait would be {wait:.0f}s)")
        time.sleep(wait)


def _daily_quota(text):
    t = text or ""
    return "PerDay" in t or "per day" in t.lower()


def _retry_delay(text):
    """Gemini puts the wait in the body: "retryDelay": "37s" (or "Please retry in 36.5s")."""
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', text or "") or \
        re.search(r"retry in (\d+(?:\.\d+)?)s", text or "")
    return float(m.group(1)) + 1 if m else None


def _quota_summary(text):
    m = re.search(r'"quotaId"\s*:\s*"([^"]+)"', text or "")
    v = re.search(r'"quotaValue"\s*:\s*"(\d+)"', text or "")
    d = _retry_delay(text)
    return (f"{m.group(1) if m else 'daily quota'}"
            + (f", limit {v.group(1)}" if v else "")
            + (f", resets in about {d / 3600:.1f} h" if d else ""))


class RequestBudget:
    """D23: a local count of HTTP attempts per model per Pacific-time day (the reset Google uses),
    kept in cache/requests.json so it survives restarts. take() raises RateLimitStop *before* an
    attempt that would exceed `rpd`. rpd=0 disables it. Pacific time is taken as UTC-8 all year
    (off by one hour during US daylight saving time; the provider's own 429 is the backstop)."""

    def __init__(self, rpd=0, path=None):
        self.rpd = rpd
        self.path = path or (CACHE_DIR / "requests.json")

    @staticmethod
    def day():
        from datetime import datetime, timedelta, timezone
        return datetime.now(timezone(timedelta(hours=-8))).strftime("%Y-%m-%d")

    def _load(self):
        try:
            return json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def used(self, model):
        return self._load().get(self.day(), {}).get(model, 0)

    def take(self, model):
        if not self.rpd:
            return
        data = self._load()
        today = data.setdefault(self.day(), {})
        if today.get(model, 0) >= self.rpd:
            raise RateLimitStop(f"daily request budget reached: {today[model]} of {self.rpd} "
                                f"attempts used today (Pacific) for {model}")
        today[model] = today.get(model, 0) + 1
        Path(self.path).parent.mkdir(exist_ok=True)
        tmp = Path(self.path).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)


BUDGET = RequestBudget(rpd=0)  # the CLI sets --rpd; tests stay unbudgeted


def call_agent(model, temperature, messages, call_id, reasoning_effort=None, post=None,
               max_tokens=None):
    """Return a call record. Cached responses are replayed; failed calls are never cached.

    A non-retryable API error returns a record with error set (raw_text None).
    RateLimitStop and RequestTooLarge propagate: the run stops and is resumed later.
    """
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    key = cache_key(model, temperature, reasoning_effort, messages, call_id, max_tokens)
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        return {**record, "cached": True}
    estimate = PACER.estimate(messages)
    PACER.wait_for(estimate + (max_tokens or 0) if PACER.combined else estimate)
    try:
        record = call_model(model, temperature, reasoning_effort, messages, post=post,
                            max_tokens=max_tokens)
    except RequestTooLarge:
        raise  # rejected before processing: nothing counted against the window
    except CallFailed as e:
        PACER.record(estimate)
        return {"raw_text": None, "reasoning": None, "finish_reason": None,
                "prompt_tokens": 0, "completion_tokens": 0,
                "latency_ms": None, "retries": e.retries, "error": str(e), "cached": False}
    if PACER.combined:
        PACER.record((record["prompt_tokens"] or estimate) + (record["completion_tokens"] or 0))
    else:
        PACER.record(record["prompt_tokens"] or estimate, record["completion_tokens"] or 0)
    record["error"] = None
    record.update(model=model, temperature=temperature, reasoning_effort=reasoning_effort,
                  max_tokens=max_tokens,
                  call_id=call_id, endpoint=ENDPOINT)
    CACHE_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
    os.replace(tmp, path)  # atomic: an interrupted write never leaves a half cache file
    return {**record, "cached": False}


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text):
    """Return the last top-level JSON array or object in `text`, or None.

    Ignores <think> blocks. Prefers fenced ```json blocks; otherwise scans for the last
    decodable value starting at '[' or '{'. Lenient by design: format is not under test.
    """
    if not text:
        return None
    text = _THINK.sub("", text)
    for block in reversed(_FENCE.findall(text)):
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    found = None
    i = 0
    while i < len(text):
        if text[i] in "[{":
            try:
                value, end = decoder.raw_decode(text, i)
                found = value
                i = end
                continue
            except json.JSONDecodeError:
                pass
        i += 1
    return found
