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
DEFAULT_ENDPOINT = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "qwen/qwen3.8-27b"
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
    """The prompt exceeds the provider's per-request or per-minute token limit. Retrying cannot help."""


def set_endpoint(url):
    """Point every call in this process at an OpenAI-compatible API (the --endpoint flag)."""
    global ENDPOINT, _client
    ENDPOINT, _client = url.rstrip("/"), None


def cache_key(model, temperature, reasoning_effort, messages, call_id):
    """call_id = [task_id, role, index]: identical prompts in different roles never share a response."""
    payload = json.dumps([model, temperature, reasoning_effort, messages, call_id, ENDPOINT])
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
        _client = httpx.Client(base_url=ENDPOINT, headers=headers, timeout=300)
    return _client


def _too_large(status, text):
    return status == 413 or "request too large" in (text or "").lower()


def call_model(model, temperature, reasoning_effort, messages, post=None):
    """One POST to {ENDPOINT}/chat/completions. Fresh context: only `messages`, no history.

    Retries only when no model response arrived: 429, 5xx, connection error, timeout.
    `post` is injectable for tests; it takes the JSON body and returns an httpx-like response.
    """
    import httpx

    post = post or (lambda body: client().post("/chat/completions", json=body))
    body = {"model": model, "temperature": temperature, "messages": messages}
    if reasoning_effort is not None:
        body["reasoning_effort"] = reasoning_effort
    for attempt in range(MAX_RETRIES + 1):
        start = time.perf_counter()
        try:
            resp = post(body)
        except httpx.TransportError as e:
            resp, error = None, f"{type(e).__name__}: {e}"
        else:
            error = f"HTTP {resp.status_code}: {resp.text[:400]}"
            if resp.status_code == 200:
                data = resp.json()
                message, usage = data["choices"][0]["message"], data.get("usage") or {}
                return {
                    "raw_text": message.get("content"),
                    "reasoning": message.get("reasoning"),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "latency_ms": round((time.perf_counter() - start) * 1000),
                    "retries": attempt,
                }
            if _too_large(resp.status_code, resp.text):
                raise RequestTooLarge(error)
            if resp.status_code != 429 and resp.status_code < 500:
                raise CallFailed(error, attempt)
        wait = 2 ** attempt
        if resp is not None and resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", wait))
        if attempt == MAX_RETRIES or wait > MAX_WAIT_S:
            raise RateLimitStop(f"{error} after {attempt} retries (next wait would be {wait:.0f}s)")
        time.sleep(wait)


def call_agent(model, temperature, messages, call_id, reasoning_effort=None, post=None):
    """Return a call record. Cached responses are replayed; failed calls are never cached.

    A non-retryable API error returns a record with error set (raw_text None).
    RateLimitStop and RequestTooLarge propagate: the run stops and is resumed later.
    """
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    key = cache_key(model, temperature, reasoning_effort, messages, call_id)
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        return {**record, "cached": True}
    try:
        record = call_model(model, temperature, reasoning_effort, messages, post=post)
    except CallFailed as e:
        return {"raw_text": None, "reasoning": None, "prompt_tokens": 0, "completion_tokens": 0,
                "latency_ms": None, "retries": e.retries, "error": str(e), "cached": False}
    record["error"] = None
    record.update(model=model, temperature=temperature, reasoning_effort=reasoning_effort,
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
