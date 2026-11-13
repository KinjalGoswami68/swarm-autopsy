import json

import pytest

import agent
import ledger
import swarm

CFG = dict(model="m", temperature=0, reasoning_effort=None, workers=4, max_tokens=None)


class FakeModel:
    """Replies by role (call_id[1]); records every prompt. `too_large` holds roles/worker ids to reject."""

    def __init__(self, task, plan, worker_reply=None, merger_reply=None, too_large=()):
        self.task, self.plan, self.too_large = task, plan, set(too_large)
        self.worker_reply = worker_reply or self._honest_worker
        self.merger_reply = merger_reply
        self.prompts = []

    def _honest_worker(self, prompt):
        key = {k["line_id"]: k["shortfall_cents"] for k in self.task["key"]}
        found = [{"line_id": i, "shortfall": v / 100} for i, v in key.items() if f",{i}," in prompt]
        return json.dumps(found)

    def __call__(self, model, temperature, prompt, call_id, reasoning_effort=None, max_tokens=None):
        self.prompts.append(prompt)
        role = call_id[1]
        tag = role if role != "worker" else f"worker{call_id[3]}"
        if tag in self.too_large or role in self.too_large:
            raise agent.RequestTooLarge("Request too large on input tokens per minute (ITPM): Limit 7000, Requested 9000")
        if role == "planner":
            text = self.plan
        elif role == "worker":
            text = self.worker_reply(prompt)
        elif role == "merger":
            text = self.merger_reply(prompt) if self.merger_reply else _union(prompt)
        else:
            text = "[]"
        return {"raw_text": text, "reasoning": None, "finish_reason": "stop", "prompt_tokens": 1,
                "completion_tokens": 1, "latency_ms": 1, "retries": 0, "cached": False,
                "error": None}


def _union(prompt):
    items = {}
    for line in prompt.splitlines():
        if line.startswith("Worker ") and "[" in line:
            for it in json.loads(line.split(": ", 1)[1]):
                items[it["line_id"]] = it
    return json.dumps(list(items.values()))


def even_plan(n, w=4, extra=0):
    step = n // w
    entries = [{"worker": i + 1, "brief": "Find underpaid lines (paid < qty x unit_rate).",
                "ranges": [[i * step + 1, n if i == w - 1 else (i + 1) * step]]} for i in range(w)]
    entries += [{"worker": w + j + 1, "brief": "extra", "ranges": [[1, 2]]} for j in range(extra)]
    return json.dumps({"workers": entries})


@pytest.fixture
def task():
    return ledger.generate("S", 1)


def run(monkeypatch, fake, task):
    monkeypatch.setattr(agent, "call_agent", fake)
    return swarm.run_task(task, CFG)


def test_perfect_swarm_keeps_everything(monkeypatch, task):
    fake = FakeModel(task, even_plan(60))
    r = run(monkeypatch, fake, task)
    assert {i["id"] for i in r["swarm"]["merger"]["final"]} == {k["id"] for k in r["items"]["key"]}
    assert len(r["swarm"]["workers"]) == 4
    assert sum(len(w["slice"]) for w in r["swarm"]["workers"]) == 60
    assert r["baseline"]["status"] == "ok"


def test_key_shortfalls_never_in_prompts(monkeypatch, task):
    fake = FakeModel(task, even_plan(60), worker_reply=lambda p: "[]")
    run(monkeypatch, fake, task)
    for k in task["key"]:
        needle = ledger.money(k["shortfall_cents"])
        assert all(needle not in p for p in fake.prompts)
    assert all("planted" not in p.lower() for p in fake.prompts)


def test_planner_prompt_has_headers_not_rows(task):
    p = swarm.planner_prompt(task, 4)
    assert ledger.header() in p and "60 lines" in p
    assert all(r["line_id"] not in p for r in task["rows"])


def test_worker_prompt_has_only_brief_and_slice(task):
    rows = task["rows"][:5]
    p = swarm.worker_prompt("BRIEF", rows)
    assert p.startswith("BRIEF") and ledger.TASK_TEXT not in p
    assert all(r["line_id"] not in p for r in task["rows"][5:])


def test_unparseable_planner_calls_no_workers(monkeypatch, task):
    fake = FakeModel(task, "I will split it evenly.")
    r = run(monkeypatch, fake, task)
    assert r["swarm"]["workers"] == [] and r["swarm"]["merger"]["status"] == "not_called"
    assert r["swarm"]["planner"]["status"] == "unparseable"


def test_extra_briefs_ignored_and_logged(monkeypatch, task):
    r = run(monkeypatch, FakeModel(task, even_plan(60, extra=2)), task)
    assert len(r["swarm"]["workers"]) == 4
    assert sum("ignored" in n for n in r["swarm"]["planner"]["parse_notes"]) == 2


def test_worker_too_large_is_recorded_and_run_continues(monkeypatch, task):
    fake = FakeModel(task, even_plan(60), too_large={"worker2"})
    r = run(monkeypatch, fake, task)
    w2 = r["swarm"]["workers"][1]
    assert w2["status"] == "rejected_too_large" and w2["reported"] == []
    assert "worker call rejected: request too large" in w2["parse_notes"][0]
    assert w2["call"]["requested_tokens"] == 9000 and w2["call"]["limit_tokens"] == 7000
    assert r["swarm"]["merger"]["status"] == "ok"


def test_baseline_too_large_has_no_score(monkeypatch, task):
    r = run(monkeypatch, FakeModel(task, even_plan(60), too_large={"baseline"}), task)
    b = r["baseline"]
    assert b["status"] == "rejected_too_large" and b["final"] is None
    assert "did not fit in one call" in b["parse_notes"][0]


def test_rate_limit_stop_propagates(monkeypatch, task):
    def stop(*a, **k):
        raise agent.RateLimitStop("429")
    monkeypatch.setattr(agent, "call_agent", stop)
    with pytest.raises(agent.RateLimitStop):
        swarm.run_task(task, CFG)


def test_parse_plan_clamps_and_drops():
    text = json.dumps({"workers": [{"brief": "a", "ranges": [[50, 10], [55, 99], [70, 80], ["x", 2]]}]})
    plan, notes = swarm.parse_plan(text, 60, 4)
    assert plan[0]["ranges"] == [[10, 50], [55, 60]]
    assert any("outside" in n for n in notes) and any("malformed" in n for n in notes)


@pytest.mark.parametrize("text,ids,values", [
    ('[{"line_id":"rx-abcde","shortfall":"1,234.50"}]', ["RX-ABCDE"], [123450]),
    ('{"underpaid":[{"line_id":"RX-AAAAA","shortfall":2}]}', ["RX-AAAAA"], [200]),
    ('[{"line_id":"RX-A","shortfall":1},{"line_id":"RX-A","shortfall":1},{"x":1}]', ["RX-A"], [100]),
    ('[{"line_id":"RX-B","shortfall":"n/a"}]', ["RX-B"], [None]),
])
def test_parse_items(text, ids, values):
    items, _, _ = swarm.parse_items(text)
    assert [i["id"] for i in items] == ids and [i["value"] for i in items] == values


def test_parse_items_none_when_no_array():
    assert swarm.parse_items("nothing")[0] is None


def test_nonpositive_shortfall_counts_as_not_reported():
    text = ('[{"line_id":"RX-A","shortfall":0.00},{"line_id":"RX-B","shortfall":-3},'
            '{"line_id":"RX-C","shortfall":"12.50"},{"line_id":"RX-D","shortfall":"?"}]')
    items, notes, dropped = swarm.parse_items(text)
    assert [i["id"] for i in items] == ["RX-C", "RX-D"] and dropped == 2
    assert any("counted as not reported" in n for n in notes)


def test_dropped_count_and_raw_reply_kept_in_run(monkeypatch, task):
    reply = lambda p: '[{"line_id":"RX-ZZZZZ","shortfall":0}]'
    r = run(monkeypatch, FakeModel(task, even_plan(60), worker_reply=reply), task)
    w = r["swarm"]["workers"][0]
    assert w["nonpositive_dropped"] == 1 and w["reported"] == []
    assert "RX-ZZZZZ" in w["call"]["raw_text"]


def test_format_line_asks_for_positive_only():
    assert "greater than 0" in swarm.ITEM_FORMAT and "Do not show your working" in swarm.ITEM_FORMAT


def test_truncated_reply_salvages_complete_entries():
    text = ('[\n{"line_id":"RX-A","shortfall":5.00},\n{"line_id":"RX-B","shortfall":0},\n'
            '{"line_id":"RX-C","sho')
    items, notes, dropped = swarm.parse_items(text, truncated=True)
    assert [i["id"] for i in items] == ["RX-A"] and dropped == 1
    assert any("cut off" in n for n in notes)
    assert swarm.parse_items(text)[0] is None  # not salvaged unless the provider cut it off


def test_truncated_status_kept_even_with_salvage():
    call = {"finish_reason": "length", "rejected_too_large": False, "error": None}
    assert swarm._status(call, [{"id": "A", "value": 1}]) == "truncated"


def test_max_tokens_total_leaves_room_for_input():
    cfg = dict(CFG, max_tokens_total=8000)
    prompt = "x" * 3000  # estimated 2100 input tokens
    mt = swarm.max_tokens_for(cfg, prompt)
    assert mt == 8000 - (2000 + 100) - 100
    assert swarm.max_tokens_for(CFG, prompt) is None
