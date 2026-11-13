"""Swarm runner (planner -> workers -> merger) and single-agent baseline on one ledger task."""
import json
import re
from datetime import datetime, timezone

import agent
import ledger

SCHEMA_VERSION = 1

ANSWER_ONLY = "Do not show your working or any explanation."  # D12: free-tier output cap

ITEM_FORMAT = (
    ANSWER_ONLY + ' Reply with only a JSON array. Each element is '
    '{"line_id": "<line_id>", "shortfall": <amount with two decimals>}. '
    'List only lines whose shortfall is greater than 0. '  # D13
    'Use [] if there are none.'
)


def planner_prompt(task, workers):
    return (
        f"{ledger.TASK_TEXT}\n\n"
        f"The ledger has {task['n_lines']} lines, numbered row 1 to row {task['n_lines']}. "
        f"Its columns are:\n{ledger.header()}\n"
        "You will not see the rows themselves.\n\n"
        f"You coordinate {workers} workers. Each worker receives only the brief you write for it and "
        "the ledger rows you assign to it, given as inclusive row ranges. Workers cannot see the "
        "task description above, each other, or any rows you do not assign to them. Their reports "
        "will then be combined into one final answer.\n\n"
        f"Write a brief for each of the {workers} workers. {ANSWER_ONLY} "
        "Reply with only a JSON object:\n"
        '{"workers": [{"worker": 1, "brief": "<instructions>", "ranges": [[<first row>, <last row>]]}, ...]}'
    )


def worker_prompt(brief, rows):
    return f"{brief}\n\nYour ledger rows:\n{ledger.render_rows(rows)}\n\n{ITEM_FORMAT}"


def merger_prompt(task, reports):
    parts = [ledger.TASK_TEXT, "",
             f"{len(reports)} workers each checked part of the ledger. You do not see the ledger. "
             "Their reports:"]
    for w, items in reports:
        if items is None:
            parts.append(f"Worker {w}: (no parseable report)")
        else:
            shown = [{"line_id": i["id"], "shortfall": _show_value(i["value"])} for i in items]
            parts.append(f"Worker {w}: {json.dumps(shown)}")
    parts += ["", "Produce the final list of underpaid lines.", ITEM_FORMAT]
    return "\n".join(parts)


def baseline_prompt(task):
    return f"{ledger.TASK_TEXT}\n\nThe ledger:\n{ledger.render_rows(task['rows'])}\n\n{ITEM_FORMAT}"


def _show_value(cents):
    return None if cents is None else round(cents / 100, 2)


_MONEY = re.compile(r"^-?\d+(\.\d+)?$")


def to_cents(v):
    """Parse a reported shortfall into integer cents, or None if it is not a number."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return round(v * 100)
    if isinstance(v, str):
        s = v.replace(",", "").replace("$", "").strip()
        if _MONEY.match(s):
            return round(float(s) * 100)
    return None


_OBJECT = re.compile(r"\{[^{}\[\]]*\}")


def salvage_entries(text):
    """D14: from a reply cut off by the output cap, the complete {...} entries before the cut."""
    out = []
    for m in _OBJECT.finditer(text or ""):
        try:
            entry = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and "line_id" in entry:
            out.append(entry)
    return out


def parse_items(text, truncated=False):
    """Parse a reply into (items, notes, nonpositive_dropped). items is None when there is no
    usable JSON list.

    truncated=True (finish_reason "length"): if the array never closed, the complete entries
    before the cut are used and noted (D14).

    Accepts a bare array, or an object whose single list value is the array. Entries without a
    string line_id are dropped and noted. Repeated ids within one reply are kept once, noted.
    D13: an entry whose own shortfall is 0 or negative is the reply saying "not underpaid", so it
    counts as not reported; the count is returned and noted. An entry whose shortfall cannot be
    read as a number still counts as reported (the reply named the line).
    """
    notes = []
    data = agent.extract_json(text)
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1:
            data = lists[0]
            notes.append("array found inside an object")
    if not isinstance(data, list) and truncated:
        data = salvage_entries(text)
        notes.append(f"reply cut off by output cap; {len(data)} complete entries before the cut used (D14)")
    if not isinstance(data, list):
        return None, notes + ["no JSON array in reply"], 0
    items, seen, nonpositive = [], set(), 0
    for entry in data:
        lid = entry.get("line_id") if isinstance(entry, dict) else None
        if not isinstance(lid, str) or not lid.strip():
            notes.append(f"dropped entry without line_id: {json.dumps(entry)[:80]}")
            continue
        lid = lid.strip().upper()
        if lid in seen:
            notes.append(f"repeated id in reply: {lid}")
            continue
        seen.add(lid)
        value = to_cents(entry.get("shortfall"))
        if value is not None and value <= 0:
            nonpositive += 1
            continue
        items.append({"id": lid, "value": value})
    if nonpositive:
        notes.append(f"{nonpositive} entries with shortfall <= 0 counted as not reported (D13)")
    return items, notes, nonpositive


def parse_plan(text, n_lines, workers):
    """Parse the planner reply into (assignments, notes). Never invents a split.

    Briefs past `workers` are ignored and noted. Ranges are clamped to 1..n_lines; reversed
    ranges are swapped; malformed ranges are dropped and noted.
    """
    notes = []
    data = agent.extract_json(text)
    if isinstance(data, dict):
        data = data.get("workers")
    if not isinstance(data, list):
        return [], ["no workers list in planner reply"]
    out = []
    for idx, entry in enumerate(data):
        if not isinstance(entry, dict):
            notes.append(f"entry {idx + 1} is not an object")
            continue
        if len(out) == workers:
            notes.append(f"brief {idx + 1} ignored: more than {workers} briefs")
            continue
        brief = entry.get("brief")
        if not isinstance(brief, str):
            brief = "" if brief is None else json.dumps(brief)
            notes.append(f"brief {idx + 1} was not a string")
        ranges = []
        for rg in entry.get("ranges") or []:
            if (isinstance(rg, list) and len(rg) == 2
                    and all(isinstance(x, int) and not isinstance(x, bool) for x in rg)):
                a, b = sorted(rg)
                a, b = max(a, 1), min(b, n_lines)
                if a <= b:
                    ranges.append([a, b])
                    if [a, b] != sorted(rg):
                        notes.append(f"brief {idx + 1}: range {rg} clamped to {[a, b]}")
                else:
                    notes.append(f"brief {idx + 1}: range {rg} outside the ledger, dropped")
            else:
                notes.append(f"brief {idx + 1}: malformed range {json.dumps(rg)[:40]} dropped")
        out.append({"brief": brief, "ranges": ranges})
    return out, notes


TOO_LARGE = "request too large"


def _call(cfg, prompt, call_id):
    """One call record. A request-too-large rejection is recorded, not raised (D9, D11).
    RateLimitStop propagates and stops the run."""
    try:
        r = agent.call_agent(cfg["model"], cfg["temperature"], prompt, call_id,
                             reasoning_effort=cfg["reasoning_effort"],
                             max_tokens=cfg.get("max_tokens"))
    except agent.RequestTooLarge as e:
        return {"prompt": prompt, "raw_text": None, "reasoning": None, "finish_reason": None,
                "prompt_tokens": 0,
                "completion_tokens": 0, "latency_ms": None, "retries": 0, "cached": False,
                "error": f"{TOO_LARGE}: {e}", "rejected_too_large": True,
                "requested_tokens": e.requested_tokens, "limit_tokens": e.limit_tokens}
    return {"prompt": prompt, "raw_text": r["raw_text"], "reasoning": r.get("reasoning"),
            "finish_reason": r.get("finish_reason"),
            "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"],
            "latency_ms": r["latency_ms"], "retries": r["retries"], "cached": r["cached"],
            "error": r["error"], "rejected_too_large": False}


def _status(call, items):
    if call is None:
        return "not_called"
    if call["rejected_too_large"]:
        return "rejected_too_large"
    if call["error"]:
        return "call_failed"
    if call.get("finish_reason") == "length":
        return "truncated"  # D14: salvaged entries (if any) are kept, the status still says cut off
    return "ok" if items is not None else "unparseable"


def run_baseline(task, cfg):
    """status "rejected_too_large" means the baseline did not fit in one call: final is None and
    it has no score (never a score of zero)."""
    call = _call(cfg, baseline_prompt(task), [task["task_id"], "baseline", 0])
    items, notes, dropped = parse_items(call["raw_text"], call.get("finish_reason") == "length")
    status = _status(call, items)
    if status == "rejected_too_large":
        notes = [f"baseline did not fit in one call: requested {call['requested_tokens']} "
                 f"input tokens, limit {call['limit_tokens']}"]
    return {"call": call, "status": status, "parsed_ok": items is not None, "parse_notes": notes,
            "nonpositive_dropped": dropped,
            "final": None if status == "rejected_too_large" else (items or [])}


def run_swarm(task, cfg):
    W = cfg["workers"]
    plan_call = _call(cfg, planner_prompt(task, W), [task["task_id"], "planner", W])
    assignments, plan_notes = parse_plan(plan_call["raw_text"], task["n_lines"], W)
    planner = {"call": plan_call, "status": _status(plan_call, assignments or None),
               "parsed_ok": bool(assignments), "parse_notes": plan_notes,
               "briefs_used": len(assignments)}

    workers, reports = [], []
    for i, a in enumerate(assignments, start=1):
        rows = ledger.rows_in_ranges(task["rows"], a["ranges"])
        call = _call(cfg, worker_prompt(a["brief"], rows), [task["task_id"], "worker", W, i])
        items, notes, dropped = parse_items(call["raw_text"], call.get("finish_reason") == "length")
        status = _status(call, items)
        if status == "rejected_too_large":
            notes = [f"worker call rejected: {TOO_LARGE} (requested {call['requested_tokens']} "
                     f"input tokens, limit {call['limit_tokens']}); treated as reporting nothing"]
        workers.append({"worker": i, "brief": a["brief"], "ranges": a["ranges"],
                        "slice": [r["line_id"] for r in rows], "call": call, "status": status,
                        "parsed_ok": items is not None, "parse_notes": notes,
                        "nonpositive_dropped": dropped, "reported": items or []})
        reports.append((i, items))

    if workers:
        m_call = _call(cfg, merger_prompt(task, reports), [task["task_id"], "merger", W])
        items, notes, dropped = parse_items(m_call["raw_text"], m_call.get("finish_reason") == "length")
        merger = {"call": m_call, "status": _status(m_call, items),
                  "parsed_ok": items is not None, "parse_notes": notes,
                  "nonpositive_dropped": dropped, "final": items or []}
    else:
        merger = {"call": None, "status": "not_called", "parsed_ok": False,
                  "parse_notes": ["merger not called: planner produced no usable briefs"],
                  "final": []}
    return {"planner": planner, "workers": workers, "merger": merger}


def _usage(calls):
    calls = [c for c in calls if c]
    return {"calls": len(calls),
            "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
            "completion_tokens": sum(c["completion_tokens"] for c in calls),
            "latency_ms": sum(c["latency_ms"] or 0 for c in calls)}


def run_id(task, cfg):
    model = re.sub(r"[^A-Za-z0-9.-]+", "_", cfg["model"])
    return f"{task['task_id']}__{model}__w{cfg['workers']}__t{cfg['temperature']}"


def run_task(task, cfg, only=None):
    """Run the swarm and the baseline on one task. Returns a run record (see SCHEMA.md).

    only="baseline" runs just the baseline (used for the size check); the result is not a full run.
    """
    baseline = run_baseline(task, cfg)
    if only == "baseline":
        return {"baseline": baseline}
    swarm = run_swarm(task, cfg)
    swarm_calls = [swarm["planner"]["call"], *[w["call"] for w in swarm["workers"]],
                   swarm["merger"]["call"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id(task, cfg),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {"model": cfg["model"], "endpoint": agent.ENDPOINT,
                   "temperature": cfg["temperature"], "reasoning_effort": cfg["reasoning_effort"],
                   "workers": cfg["workers"], "max_tokens": cfg.get("max_tokens"),
                   "itpm": cfg.get("itpm"), "otpm": cfg.get("otpm")},
        "task": {"family": task["family"], "task_id": task["task_id"], "size": task["size"],
                 "seed": task["seed"], "n_lines": task["n_lines"], "n_planted": task["n_planted"],
                 "task_text": ledger.TASK_TEXT, "columns": ledger.COLUMNS, "rows": task["rows"]},
        "items": {"universe": [r["line_id"] for r in task["rows"]],
                  "key": [{"id": k["line_id"], "value": k["shortfall_cents"]} for k in task["key"]],
                  "value_unit": "cents"},
        "swarm": swarm,
        "baseline": baseline,
        "usage": {"swarm": _usage(swarm_calls), "baseline": _usage([baseline["call"]])},
    }
