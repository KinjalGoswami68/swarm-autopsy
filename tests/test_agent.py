import json

import pytest

import agent


class Resp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code, self._payload, self.text, self.headers = status, payload, text, headers or {}

    def json(self):
        return self._payload


def ok(content="[]"):
    return Resp(200, {"choices": [{"message": {"content": content}}],
                      "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def scripted(*responses):
    calls = []
    it = iter(responses)

    def post(body):
        calls.append(body)
        return next(it)
    post.calls = calls
    return post


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)


def test_success_returns_text_and_tokens():
    r = agent.call_agent("m", 0, "hi", ["t", "x", 0], post=scripted(ok("[1]")))
    assert r["raw_text"] == "[1]" and r["prompt_tokens"] == 10 and r["retries"] == 0
    assert r["error"] is None and r["cached"] is False


def test_retries_5xx_then_succeeds():
    post = scripted(Resp(503, text="over capacity"), ok())
    r = agent.call_agent("m", 0, "hi", ["t"], post=post)
    assert r["retries"] == 1 and len(post.calls) == 2


def test_long_retry_after_stops_run():
    post = scripted(Resp(429, text="rate", headers={"retry-after": "900"}))
    with pytest.raises(agent.RateLimitStop):
        agent.call_agent("m", 0, "hi", ["t"], post=post)


def test_request_too_large_stops_without_retry():
    post = scripted(Resp(413, text="Request too large for model"))
    with pytest.raises(agent.RequestTooLarge):
        agent.call_agent("m", 0, "hi", ["t"], post=post)
    assert len(post.calls) == 1


def test_request_too_large_as_429_also_stops():
    post = scripted(Resp(429, text="Request too large: TPM limit 6000, requested 9000"))
    with pytest.raises(agent.RequestTooLarge):
        agent.call_agent("m", 0, "hi", ["t"], post=post)


def test_4xx_is_failed_call_not_cached():
    r = agent.call_agent("m", 0, "hi", ["t"], post=scripted(Resp(400, text="bad")))
    assert r["raw_text"] is None and "400" in r["error"]
    assert not (agent.CACHE_DIR.exists() and any(agent.CACHE_DIR.iterdir()))


def test_cache_replays_without_calling():
    agent.call_agent("m", 0, "hi", ["t"], post=scripted(ok("[7]")))
    r = agent.call_agent("m", 0, "hi", ["t"], post=scripted())  # would raise StopIteration if called
    assert r["cached"] is True and r["raw_text"] == "[7]"


def test_call_id_separates_cache_entries():
    agent.call_agent("m", 0, "hi", ["a"], post=scripted(ok("[1]")))
    r = agent.call_agent("m", 0, "hi", ["b"], post=scripted(ok("[2]")))
    assert r["raw_text"] == "[2]" and r["cached"] is False


def test_temperature_and_model_sent():
    post = scripted(ok())
    agent.call_agent("qwen/x", 0, "hi", ["t"], post=post)
    assert post.calls[0]["model"] == "qwen/x" and post.calls[0]["temperature"] == 0
    assert "reasoning_effort" not in post.calls[0]


@pytest.mark.parametrize("text,expected", [
    ('[{"line_id":"A","shortfall":1.5}]', [{"line_id": "A", "shortfall": 1.5}]),
    ('<think>[1,2]</think>Answer: [3]', [3]),
    ('Here:\n```json\n[{"a":1}]\n```\nDone.', [{"a": 1}]),
    ('first [1] then final [2]', [2]),
    ('no json here', None),
    ('', None),
    ('{"workers": []} trailing text', {"workers": []}),
])
def test_extract_json(text, expected):
    assert agent.extract_json(text) == expected
