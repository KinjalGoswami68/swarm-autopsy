import json
from collections import Counter

import pytest

import agent
import autopsy
import cli
import ledger2
import runfile
import swarm


@pytest.mark.parametrize("size", ["S", "M", "L"])
def test_counts_and_structure(size):
    t = ledger2.generate(size, 1)
    n, nt, k_line, k_ctx, k_far, k_near = ledger2.SIZES[size]
    assert len(t["rate_rows"]) == nt and len(t["line_rows"]) == n
    assert [r["row"] for r in t["rows"]] == list(range(1, n + nt + 1))
    types = Counter(autopsy.item_label(k) for k in t["key"])
    assert types == {"line": k_line, "context": k_ctx, "far pair": k_far, "near pair": k_near}
    coded = sum(1 for r in t["line_rows"] if r["rate_code"])
    assert 0.3 < coded / n < 0.7  # about half coded (D22)
    assert all((r["rate_code"] is None) != (r["unit_rate_cents"] is None) for r in t["line_rows"])


def test_key_values_recompute_from_table():
    t = ledger2.generate("M", 2)
    rates = {r["rate_code"]: r["unit_rate_cents"] for r in t["rate_rows"]}
    by_id = {r["line_id"]: r for r in t["line_rows"]}
    for k in t["key"]:
        if k["type"] == "pair":
            continue
        r = by_id[k["id"]]
        owed = r["qty"] * (rates[r["rate_code"]] if r["rate_code"] else r["unit_rate_cents"])
        assert k["value"] == owed - r["paid_cents"] > 0
        if k["type"] == "context":
            assert r["rate_code"] and k["needs"] == [r["line_id"], f"RATE:{r['rate_code']}"]
            assert k["context"] == [f"RATE:{r['rate_code']}"]
        else:
            assert r["rate_code"] is None and k["needs"] == [r["line_id"]]


def test_exactly_the_planted_rows_are_underpaid():
    t = ledger2.generate("L", 3)
    rates = {r["rate_code"]: r["unit_rate_cents"] for r in t["rate_rows"]}
    under = {r["line_id"] for r in t["line_rows"]
             if r["paid_cents"] < r["qty"] * (rates[r["rate_code"]] if r["rate_code"] else r["unit_rate_cents"])}
    assert under == {k["id"] for k in t["key"] if k["type"] != "pair"}


def test_pairs_share_claim_far_and_near_distances():
    t = ledger2.generate("L", 1)
    claims = Counter(r["claim_id"] for r in t["line_rows"])
    repeated = {c for c, n in claims.items() if n > 1}
    pairs = [k for k in t["key"] if k["type"] == "pair"]
    assert len(repeated) == len(pairs) and all(claims[c] == 2 for c in repeated)
    by_id = {r["line_id"]: r for r in t["line_rows"]}
    for k in pairs:
        a, b = (by_id[i] for i in k["needs"])
        assert a["claim_id"] == b["claim_id"] and a["paid_cents"] == b["paid_cents"]
        assert k["id"] == ledger2.pair_id(a["line_id"], b["line_id"])
        if k["subtype"] == "far":
            assert k["distance"] >= t["n_lines"] // 2
        else:
            assert 1 <= k["distance"] <= ledger2.NEAR_MAX


def test_deterministic():
    assert ledger2.generate("S", 5) == ledger2.generate("S", 5)
    assert ledger2.generate("S", 5)["key"] != ledger2.generate("S", 6)["key"]


def test_prompts_reveal_structure_not_answer():
    t = ledger2.generate("S", 1)
    p = ledger2.planner_prompt(t, 4)
    assert "Rows 1 to 10 are the rate table" in p and "Rows 11 to 70 are line items" in p
    assert "row,line_id,claim_id,qty,unit_rate,rate_code,paid" in p
    assert all(r["line_id"] not in p for r in t["line_rows"])
    assert all(r["rate_code"] not in p for r in t["rate_rows"])
    everything = ledger2.baseline_prompt(t) + p
    for word in ["planted", "context item", "far", "near"]:
        assert word not in everything.lower()
    for k in t["key"]:
        if k["value"] is not None:
            assert ledger2.money(k["value"]) not in everything


def test_render_slice_blocks():
    t = ledger2.generate("S", 1)
    only_lines = ledger2.render_rows(ledger2.rows_in_ranges(t["rows"], [[11, 20]]))
    assert "Rate table" not in only_lines and only_lines.startswith("Line items:")
    both = ledger2.render_rows(ledger2.rows_in_ranges(t["rows"], [[1, 10], [11, 12]]))
    assert both.startswith("Rate table:") and "Line items:" in both
    coded = next(r for r in t["line_rows"] if r["rate_code"])
    line = next(l for l in ledger2.render_rows([coded]).splitlines() if coded["line_id"] in l)
    assert line.split(",")[4] == "" and line.split(",")[5] == coded["rate_code"]


def test_parse_two_lists_and_pair_rules():
    text = json.dumps({"underpaid": [{"line_id": "rx-aaaaa", "shortfall": 3.5},
                                     {"line_id": "RX-BBBBB", "shortfall": 0}],
                       "duplicates": [{"line_ids": ["RX-ZZZZZ", "RX-CCCCC"]},
                                      {"line_ids": ["RX-CCCCC", "RX-ZZZZZ"]},
                                      {"line_ids": ["RX-DDDDD"]},
                                      {"line_ids": ["RX-EEEEE", "rx-eeeee"]}]})
    items, notes, dropped = ledger2.parse_items(text)
    assert items == [{"id": "RX-AAAAA", "value": 350, "kind": "underpaid"},
                     {"id": "PAIR:RX-CCCCC+RX-ZZZZZ", "value": None, "kind": "pair"}]
    assert dropped == 1
    assert sum("not two different line ids" in n for n in notes) == 2
    assert any("repeated pair" in n for n in notes)


def test_parse_truncated_salvage():
    text = ('{"underpaid": [{"line_id": "RX-AAAAA", "shortfall": 1.00}], "duplicates": '
            '[{"line_ids": ["RX-B", "RX-C"]}, {"line_ids": ["RX-D"')
    assert ledger2.parse_items(text)[0] is None
    items, notes, _ = ledger2.parse_items(text, truncated=True)
    assert [i["id"] for i in items] == ["RX-AAAAA", "PAIR:RX-B+RX-C"]


def test_merger_sees_pairs_in_reply_format():
    t = ledger2.generate("S", 1)
    p = ledger2.merger_prompt(t, [(1, [{"id": "PAIR:RX-A+RX-B", "value": None, "kind": "pair"},
                                       {"id": "RX-C", "value": 1234, "kind": "underpaid"}]),
                                  (2, None)])
    assert '"duplicates": [{"line_ids": ["RX-A", "RX-B"]}]' in p
    assert '{"line_id": "RX-C", "shortfall": 12.34}' in p and "Worker 2: (no parseable report)" in p


# ---------- autopsy buckets (D22) ----------

def ctx_run(workers, final, key):
    universe = ["RATE:R1", "RATE:R2", "A", "B", "C", "D", "E", "F"]
    return {
        "run_id": "r", "config": {"model": "m", "temperature": 0, "workers": len(workers)},
        "task": {"task_id": "t", "size": "S", "seed": 1, "family": "ledger-ctx"},
        "items": {"universe": universe, "key": key},
        "swarm": {"planner": {"status": "ok", "briefs_used": len(workers), "parse_notes": []},
                  "workers": [{"worker": n + 1, "brief": "b", "ranges": [], "slice": sl,
                               "reported": [{"id": i, "value": 1} for i in rep], "status": "ok",
                               "parse_notes": [], "call": {"raw_text": ""}}
                              for n, (sl, rep) in enumerate(workers)],
                  "merger": {"status": "ok", "final": [{"id": i, "value": 1} for i in final]}},
        "baseline": {"status": "ok", "call": {}, "final": []},
    }


KEY = [
    {"id": "A", "value": 1, "type": "context", "needs": ["A", "RATE:R1"], "context": ["RATE:R1"]},
    {"id": "PAIR:B+F", "value": None, "type": "pair", "subtype": "far", "needs": ["B", "F"]},
    {"id": "C", "value": 1, "type": "context", "needs": ["C", "RATE:R2"], "context": ["RATE:R2"]},
    {"id": "PAIR:D+E", "value": None, "type": "pair", "subtype": "near", "needs": ["D", "E"]},
    {"id": "G", "value": 1, "type": "line", "needs": ["G"]},
]


def test_every_new_bucket():
    # worker 1: A without its rate row, B; worker 2: table, C, D, E, F (no B)
    run = ctx_run([(["A", "B"], []), (["RATE:R1", "RATE:R2", "C", "D", "E", "F"], [])],
                  final=[], key=KEY)
    by = {p["id"]: p["bucket"] for p in autopsy.swarm_autopsy(run)["per_item"]}
    assert by == {"A": "context_not_passed", "PAIR:B+F": "evidence_split",
                  "C": "holder_returned_nothing", "PAIR:D+E": "holder_returned_nothing",
                  "G": "never_assigned"}


def test_context_row_alone_is_never_assigned():
    key = [KEY[0]]
    run = ctx_run([(["RATE:R1", "B"], [])], final=[], key=key)
    assert autopsy.swarm_autopsy(run)["per_item"][0]["bucket"] == "never_assigned"


def test_pair_with_one_row_unassigned_is_evidence_split():
    run = ctx_run([(["B"], [])], final=[], key=[KEY[1]])
    assert autopsy.swarm_autopsy(run)["per_item"][0]["bucket"] == "evidence_split"


def test_pair_complete_in_one_worker_but_cut_off_is_unreached():
    run = ctx_run([(["D", "C", "E"], [])], final=[], key=[KEY[3]])
    w = run["swarm"]["workers"][0]
    w["status"], w["call"] = "truncated", {"raw_text": '{"underpaid": [{"line_id": "D"'}
    assert autopsy.swarm_autopsy(run)["per_item"][0]["bucket"] == "assigned_unreached"


def test_half_pair_false_positive_and_by_type():
    run = ctx_run([(["B", "F", "D", "E"], [])], final=["PAIR:B+D", "PAIR:D+E", "PAIR:A+C"], key=KEY)
    s = autopsy.swarm_autopsy(run)
    kinds = {f["id"]: f["kind"] for f in s["score"]["false_positives"]}
    assert kinds == {"PAIR:B+D": "half_pair", "PAIR:A+C": "wrong_pair"}
    assert s["score"]["by_type"]["near pair"] == {"found": 1, "total": 1}
    assert s["score"]["by_type"]["context"] == {"found": 0, "total": 2}
    assert "half pair" in autopsy.render(run)


def test_schema1_run_has_no_new_buckets():
    from tests.test_autopsy import make_run
    run = make_run([(["B", "C", "E"], ["C"]), (["D", "F"], ["D"])], final=["D"])
    b = autopsy.swarm_autopsy(run)["buckets"]
    assert b["context_not_passed"] == 0 and b["evidence_split"] == 0 and b["never_assigned"] == 1


# ---------- end to end ----------

class CtxModel:
    """Planner splits rows evenly with no table; workers report what they can judge alone."""

    def __init__(self, task):
        self.task = task

    def __call__(self, model, temperature, prompt, call_id, **kw):
        role = call_id[1]
        if role == "planner":
            n = self.task["n_rows"]
            step = n // 4
            text = json.dumps({"workers": [{"worker": i + 1, "brief": "audit",
                                            "ranges": [[i * step + 1, n if i == 3 else (i + 1) * step]]}
                                           for i in range(4)]})
        elif role == "worker":
            under = [{"line_id": k["id"], "shortfall": k["value"] / 100} for k in self.task["key"]
                     if k["type"] == "line" and f",{k['id']}," in prompt]
            text = json.dumps({"underpaid": under, "duplicates": []})
        elif role == "merger":
            under = {}
            for line in prompt.splitlines():
                if line.startswith("Worker ") and "{" in line:
                    for u in json.loads(line.split(": ", 1)[1])["underpaid"]:
                        under[u["line_id"]] = u
            text = json.dumps({"underpaid": list(under.values()), "duplicates": []})
        else:
            text = json.dumps({"underpaid": [], "duplicates": []})
        return {"raw_text": text, "reasoning": None, "finish_reason": "stop", "prompt_tokens": 1,
                "completion_tokens": 1, "latency_ms": 1, "retries": 0, "cached": False, "error": None}


def test_ctx_end_to_end(monkeypatch, tmp_path, capsys):
    task = ledger2.generate("S", 1)
    monkeypatch.setattr(agent, "call_agent", CtxModel(task))
    cli.main(["run", "--family", "ledger-ctx", "--sizes", "S", "--seeds", "1",
              "--runs-dir", str(tmp_path)])
    path = next(tmp_path.glob("ledgerctx-S-s1*.json"))
    run = runfile.load(path)
    assert run["schema_version"] == 2 and run["task"]["fixed_sentence"] == ledger2.FIXED_SENTENCE
    a = autopsy.autopsy(run)["swarm"]
    # the even split gives the rate table to worker 1 only: context items in other slices fail
    assert a["buckets"]["context_not_passed"] > 0
    assert a["score"]["by_type"]["line"]["found"] == 4
    cli.main(["table", "--runs-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert ledger2.FIXED_SENTENCE in out and "lost: context not passed" in out
    cli.main(["autopsy", str(path)])
    assert ledger2.FIXED_SENTENCE in capsys.readouterr().out


# ---------- D27 brief annotations ----------
import judge


def test_quote_verified_tolerates_dash_and_space_style():
    brief = "Read rows 1‑10 of the ledger (the rate table).  Return the completed map."
    assert judge.quote_verified("Read rows 1-10 of the ledger (the rate table).", brief)
    assert judge.quote_verified("return the completed map", brief)
    assert not judge.quote_verified("Use worker 1's output.", brief)
    assert not judge.quote_verified("", brief)


def test_judge_prompt_states_slice_facts():
    task = ledger2.generate("S", 1)
    run = {"task": ledger2.task_block(task), "run_id": "r"}
    p = judge.judge_prompt(run, {"brief": "B", "ranges": [[11, 30]]})
    assert "Rows given to this worker: 11 to 30. These rows do not include the rate table" in p
    p = judge.judge_prompt(run, {"brief": "B", "ranges": [[1, 35]]})
    assert "These rows include the rate table" in p


def test_annotate_stores_and_never_changes_score(monkeypatch, tmp_path):
    task = ledger2.generate("S", 1)
    monkeypatch.setattr(agent, "call_agent", CtxModel(task))
    cli.main(["run", "--family", "ledger-ctx", "--sizes", "S", "--seeds", "1", "--runs-dir", str(tmp_path)])
    path = next(tmp_path.glob("*.json"))
    before = autopsy.autopsy(runfile.load(path))

    def fake_judge(model, temperature, prompt, call_id, **kw):
        assert call_id[0] == "judge"
        return {"raw_text": json.dumps({"a": {"answer": "yes", "quote": "audit"},
                                        "b": {"answer": "no", "quote": "", "kinds": ["underpaid"]}}),
                "error": None, "prompt_tokens": 1, "completion_tokens": 1, "cached": False}
    monkeypatch.setattr(agent, "call_agent", fake_judge)
    cli.main(["annotate", str(path), "--tpm", "0"])
    run = runfile.load(path)
    assert run["annotations"]["briefs"][0]["relies_on_missing"] == {
        "answer": "yes", "quote": "audit", "quote_verified": True}
    assert autopsy.autopsy(run) == before
    assert "why (model-read annotation): relies on something not given: yes" in autopsy.render(run)
    assert "model-read annotations" in cli.why_table([run])


def test_b_derived_from_kinds_list():
    brief = "Report underpaid lines. Report duplicates within your rows."
    text = json.dumps({"a": {"answer": "no", "quote": ""},
                       "b": {"answer": "yes", "quote": "Report duplicates within your rows.",
                             "kinds": ["underpaid", "duplicates"]}})
    b = judge.parse_judgement(text, brief, ["underpaid", "duplicates"])["b"]
    assert b["answer"] == "no" and b["judge_answer"] == "yes"
    text = json.dumps({"a": {"answer": "no", "quote": ""},
                       "b": {"answer": "no", "quote": "", "kinds": []}})
    assert judge.parse_judgement(text, "No further output.", ["underpaid", "duplicates"])["b"]["answer"] == "yes"
    text = json.dumps({"a": {"answer": "no", "quote": ""}, "b": {"answer": "yes", "quote": "x"}})
    assert judge.parse_judgement(text, "x", ["underpaid", "duplicates"])["b"]["answer"] == "yes"  # no list: fallback
