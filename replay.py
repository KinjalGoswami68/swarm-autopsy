"""Stage 2: replays (DECISIONS D29). A replay re-runs part of a stored run with one thing changed
and is stored as a labelled counterfactual beside the original; the original is never changed.

  R1 table to everyone   planner's slices unchanged + rate-table rows added to every slice
  R2 neutral briefs      planner's slices unchanged, every brief replaced by NEUTRAL_BRIEF
  R3 both                R1 and R2 together
  R4 planner told truth  the frozen planner prompt + TRUTH_SENTENCE; new planner call

Workers and merger are re-run with the run's own model and settings. A worker or merger prompt
that is byte-identical to the original's reuses the original output (flagged
`reused_from_original`), so a difference comes only from the change, not from re-sampling.
"""
import copy
from datetime import datetime, timezone
from pathlib import Path

import agent
import ledger
import ledger2
import swarm

REPLAYS = {
    "R1": "table to everyone",
    "R2": "neutral briefs",
    "R3": "table to everyone + neutral briefs",
    "R4": "planner told the truth",
}
# Frozen wording (D29), from the owner's instruction.
NEUTRAL_BRIEF = ("Report every underpaid line and every duplicate claim you can establish from the "
                 "rows you were given; you cannot see anything else and cannot contact other workers.")
TRUTH_SENTENCE = ("Workers cannot communicate with each other, and each worker sees only its own "
                  "rows.")
_ANCHOR = "Their reports will then be combined into one final answer."

REPLAY_DIR = Path(__file__).parent / "runs" / "replays"
# Guidance replays (D37) live apart from R1-R4 so build_site.py does not publish them yet.
GUIDANCE_DIR = Path(__file__).parent / "runs" / "guidance"
GUIDANCE_LINE = "Delegation guidance:"
R5_FILE = Path(__file__).parent / "protocol" / "acyclic-delegation.md"
R5_NAME = "Acyclic delegation guidance"


def git_blob_sha(data):
    """The id git gives these bytes as a blob (same as `git hash-object --no-filters`)."""
    import hashlib
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def load_guidance(path, label=None, name=None):
    """Planner guidance read byte for byte from `path` (D37). Label defaults to G-<blob prefix>."""
    path = Path(path)
    data = path.read_bytes()
    sha = git_blob_sha(data)
    try:
        shown = path.resolve().relative_to(Path(__file__).parent.resolve()).as_posix()
    except ValueError:
        shown = path.name
    return {"label": label or f"G-{sha[:8]}", "name": name or f"planner guidance from {path.name}",
            "text": data.decode("utf-8"), "file": shown, "git_blob": sha, "bytes": len(data)}


def r5_guidance():
    return load_guidance(R5_FILE, "R5", R5_NAME)


def guidance_planner_prompt(task, workers, text):
    """The frozen planner prompt with the guidance text appended verbatim under GUIDANCE_LINE."""
    return f"{ledger2.planner_prompt(task, workers)}\n\n{GUIDANCE_LINE}\n{text}"


def regenerate(run):
    t = run["task"]
    gen = {ledger2.FAMILY: ledger2.generate, "remittance-ledger": ledger.generate}[t["family"]]
    task = gen(t["size"], t["seed"])
    assert task["rows"] == t["rows"], "stored task rows differ from the generator"
    return task


def truth_planner_prompt(task, workers):
    """The frozen planner prompt with TRUTH_SENTENCE inserted after the sentence about combining."""
    p = ledger2.planner_prompt(task, workers)
    assert p.count(_ANCHOR) == 1
    return p.replace(_ANCHOR, f"{_ANCHOR} {TRUTH_SENTENCE}")


def _cfg(run):
    c = run["config"]
    return {"model": c["model"], "temperature": c["temperature"],
            "reasoning_effort": c["reasoning_effort"], "workers": c["workers"],
            "max_tokens": c.get("max_tokens"), "max_tokens_total": c.get("max_tokens_total")}


def _reused(orig_stage):
    out = copy.deepcopy(orig_stage)
    out["reused_from_original"] = True
    return out


def replay(run, label, guidance=None):
    """Return the replay record for `label` (see module docstring). Model calls are cached.
    With `guidance` (load_guidance()), the planner prompt gets that text appended (D37)."""
    if guidance:
        label = guidance["label"]
    else:
        assert label in REPLAYS
    task = regenerate(run)
    fam = swarm.family(task)
    cfg = _cfg(run)
    W = cfg["workers"]
    tid = task["task_id"]
    orig = run["swarm"]

    new_planner = label == "R4" or bool(guidance)
    # D29 reuse rule: a byte-identical worker/merger prompt reuses the original output. Applied to
    # guidance replays (D37); the R4 code never applied it, and stays as it ran.
    reuse_ok = label != "R4"
    if new_planner:
        prompt = guidance_planner_prompt(task, W, guidance["text"]) if guidance else truth_planner_prompt(task, W)
        plan_call = swarm._call(cfg, prompt, [tid, "replay", label, "planner", W])
        assignments, notes = swarm.parse_plan(plan_call["raw_text"], fam.n_rows(task), W)
        planner = {"call": plan_call, "status": swarm._status(plan_call, assignments or None),
                   "parsed_ok": bool(assignments), "parse_notes": notes,
                   "briefs_used": len(assignments)}
    else:
        assignments = [{"brief": w["brief"], "ranges": w["ranges"]} for w in orig["workers"]]
        planner = _reused(orig["planner"])

    n_rate = task.get("n_rate_codes", 0)
    workers, reports = [], []
    for i, a in enumerate(assignments, start=1):
        ranges, brief = [list(r) for r in a["ranges"]], a["brief"]
        if label in ("R1", "R3") and n_rate:
            ranges = [[1, n_rate]] + ranges
        if label in ("R2", "R3"):
            brief = NEUTRAL_BRIEF
        rows = fam.rows_in_ranges(task["rows"], ranges)
        prompt = fam.worker_prompt(brief, rows)
        before = orig["workers"][i - 1] if reuse_ok and i <= len(orig["workers"]) else None
        if before and before["call"] and before["call"]["prompt"] == prompt:
            w = _reused(before)
            w["ranges"] = ranges
        else:
            call = swarm._call(cfg, prompt, [tid, "replay", label, "worker", W, i])
            items, notes, dropped = fam.parse_items(call["raw_text"], call.get("finish_reason") == "length")
            status = swarm._status(call, items)
            if status == "rejected_too_large":
                notes = [f"worker call rejected: {swarm.TOO_LARGE}; treated as reporting nothing"]
            w = {"worker": i, "brief": brief, "ranges": ranges,
                 "slice": [fam.row_id(r) for r in rows], "call": call, "status": status,
                 "parsed_ok": items is not None, "parse_notes": notes,
                 "nonpositive_dropped": dropped, "reported": items or [],
                 "reused_from_original": False}
        workers.append(w)
        reports.append((i, w["reported"] if w["parsed_ok"] else None))

    if workers:
        m_prompt = fam.merger_prompt(task, reports)
        om = orig["merger"]
        if reuse_ok and om.get("call") and om["call"]["prompt"] == m_prompt:
            merger = _reused(om)
        else:
            m_call = swarm._call(cfg, m_prompt, [tid, "replay", label, "merger", W])
            items, notes, dropped = fam.parse_items(m_call["raw_text"], m_call.get("finish_reason") == "length")
            merger = {"call": m_call, "status": swarm._status(m_call, items),
                      "parsed_ok": items is not None, "parse_notes": notes,
                      "nonpositive_dropped": dropped, "final": items or [],
                      "reused_from_original": False}
    else:
        merger = {"call": None, "status": "not_called", "parsed_ok": False,
                  "parse_notes": ["merger not called: planner produced no usable briefs"], "final": []}

    rec = copy.deepcopy(run)
    rec.pop("annotations", None)  # they describe the original briefs, not these
    rec["run_id"] = f"{run['run_id']}__{label}"
    rec["created_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec["swarm"] = {"planner": planner, "workers": workers, "merger": merger}
    if guidance:
        change = (f"planner prompt + a line \"{GUIDANCE_LINE}\" + {guidance['file']} verbatim "
                  f"({guidance['bytes']} bytes, git blob {guidance['git_blob']})")
        name = guidance["name"]
    else:
        change = {"R1": "rate-table rows added to every worker's slice",
                  "R2": f"every brief replaced by: {NEUTRAL_BRIEF}",
                  "R3": "R1 and R2 together",
                  "R4": f"planner prompt + sentence: {TRUTH_SENTENCE}"}[label]
        name = REPLAYS[label]
    rec["replay"] = {"of": run["run_id"], "label": label, "name": name, "change": change,
                     "baseline": "copied from the original run (not re-run)"}
    if guidance:
        rec["replay"]["guidance"] = {k: guidance[k] for k in ("file", "git_blob", "bytes", "text")}
    calls = [planner.get("call") if new_planner else None,
             *[w["call"] for w in workers if not w.get("reused_from_original")],
             merger.get("call") if not merger.get("reused_from_original") else None]
    rec["usage"] = {"replay_new_calls": swarm._usage(calls)}
    return rec


def path_for(run, label, guidance=None):
    return (GUIDANCE_DIR if guidance else REPLAY_DIR) / f"{run['run_id']}__{label}.json"
