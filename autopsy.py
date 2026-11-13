"""Autopsy of one run: attribute every lost key item to split, child (worker) or merge. No model calls.

Reads only the generic fields of a run file (items, swarm, baseline), so it works for any task
family that fills them (see SCHEMA.md).
"""
import re
from collections import Counter

BUCKETS = ["never_assigned", "assigned_unreached", "assigned_missed", "dropped_at_merge", "kept"]
LOSS_BUCKETS = BUCKETS[:4]
BUCKET_LABEL = {"never_assigned": "never assigned (split)",
                "assigned_unreached": "assigned, unreached (reply cut off)",
                "assigned_missed": "assigned, missed (worker)",
                "dropped_at_merge": "found, dropped at merge (merge)",
                "kept": "found and kept"}
VALUE_TOLERANCE = 1  # cents (D7)


def _norm(i):
    return i.strip().upper()


def _ids(items):
    return [_norm(i["id"]) for i in items]


def reached_ids(order, call, status):
    """D17: the ids of `order` a reply reached. None = all of them (the reply was not cut off).

    For a truncated reply: every id up to and including the last id of `order` that appears
    anywhere in the reply text (dropped entries included, since the reply did reach them)."""
    if status != "truncated":
        return None
    raw = ((call or {}).get("raw_text") or "").upper()
    order = [_norm(i) for i in order]
    # whole-token match: an id must not be part of a longer word ("A" is not found in "SHORTFALL")
    tokens = set(re.findall(r"[A-Z0-9][A-Z0-9_-]*[A-Z0-9]|[A-Z0-9]", raw))
    last = max((k for k, i in enumerate(order) if i in tokens), default=-1)
    return set(order[:last + 1])


def bucket_of(item, slices, reported_sets, final_ids, reached=None):
    """Exactly one bucket, checked in order: kept, dropped at merge, assigned (unreached or missed),
    never assigned. Unreached only when every worker holding the item was cut off before it."""
    if item in final_ids:
        return "kept"
    if any(item in rep for rep in reported_sets):
        return "dropped_at_merge"
    reached = reached or [None] * len(slices)
    holders = [r for sl, r in zip(slices, reached) if item in sl]
    if not holders:
        return "never_assigned"
    if all(r is not None and item not in r for r in holders):
        return "assigned_unreached"
    return "assigned_missed"


def _ratio(a, b):
    return None if b == 0 else a / b


def _value_accuracy(found_ids, reported_values, key_values):
    """Share of found key items whose reported value is within tolerance (None if none found)."""
    ok = sum(1 for i in found_ids if reported_values.get(i) is not None
             and abs(reported_values[i] - key_values[i]) <= VALUE_TOLERANCE)
    return {"accurate": ok, "found": len(found_ids), "rate": _ratio(ok, len(found_ids))}


def _score(final_items, key_values, universe):
    final_ids = list(dict.fromkeys(_ids(final_items)))  # dedupe, keep order
    values = {}
    for it in final_items:
        values.setdefault(_norm(it["id"]), it.get("value"))
    key = set(key_values)
    tp = [i for i in final_ids if i in key]
    fps = [i for i in final_ids if i not in key]
    return {
        "recall": _ratio(len(tp), len(key)),
        "precision": _ratio(len(tp), len(final_ids)),
        "true_positives": len(tp),
        "final_count": len(final_ids),
        "duplicates_in_final": len(final_items) - len(final_ids),
        "false_positives": [{"id": i, "kind": "real_line" if i in universe else "nonexistent_id"}
                            for i in fps],
        "value_accuracy": _value_accuracy(tp, values, key_values),
    }


def swarm_autopsy(run):
    key_values = {_norm(k["id"]): k.get("value") for k in run["items"]["key"]}
    universe = {_norm(i) for i in run["items"].get("universe") or []}
    sw = run["swarm"]
    workers = sw["workers"]
    slices = [{_norm(i) for i in w["slice"]} for w in workers]
    reported = [set(_ids(w["reported"])) for w in workers]
    final_items = sw["merger"]["final"]
    final_ids = set(_ids(final_items))

    reached = [reached_ids(w["slice"], w.get("call"), w.get("status")) for w in workers]
    per_item = []
    for item in key_values:
        b = bucket_of(item, slices, reported, final_ids, reached)
        per_item.append({
            "id": item, "bucket": b,
            "in_slices": [w["worker"] for w, sl in zip(workers, slices) if item in sl],
            "reported_by": [w["worker"] for w, rep in zip(workers, reported) if item in rep],
        })
    counts = Counter(p["bucket"] for p in per_item)

    slice_count = Counter(i for sl in slices for i in sl)
    all_ids = universe or set(slice_count)
    score = _score(final_items, key_values, universe)
    any_reported = set().union(*reported) if reported else set()
    fp_kept, fp_merger = [], []
    for fp in score["false_positives"]:
        (fp_kept if fp["id"] in any_reported else fp_merger).append(fp)
    worker_fps = any_reported - set(key_values)

    notes = []
    for p in per_item:
        if p["bucket"] == "kept" and not p["reported_by"]:
            notes.append(f"{p['id']} kept although no worker reported it (merger guess)")
        stray = [w for w in p["reported_by"] if w not in p["in_slices"]]
        if stray:
            notes.append(f"{p['id']} reported by worker(s) {stray} that were not given it")

    flags = []
    if sw["planner"].get("status") != "ok":
        flags.append(f"planner {sw['planner'].get('status')}: no usable split")
    for w in workers:
        if w.get("status") != "ok":
            flags.append(f"worker {w['worker']} {w.get('status')}")
    if sw["merger"].get("status") not in ("ok", None):
        flags.append(f"merger {sw['merger'].get('status')}")

    return {
        "key_count": len(key_values),
        "buckets": {b: counts.get(b, 0) for b in BUCKETS},
        "lost": sum(counts.get(b, 0) for b in LOSS_BUCKETS),
        "per_item": per_item,
        "coverage": {
            "lines": len(all_ids),
            "lines_unassigned": sum(1 for i in all_ids if slice_count[i] == 0),
            "lines_in_2plus_slices": sum(1 for c in slice_count.values() if c >= 2),
            "key_lines_in_2plus_slices": sum(1 for i in key_values if slice_count[i] >= 2),
        },
        "false_positives": {"worker_reported_kept": fp_kept, "invented_by_merger": fp_merger,
                            "worker_fps_filtered_by_merger": len(worker_fps - final_ids)},
        "score": score,
        "flags": flags,
        "notes": notes,
    }


def baseline_autopsy(run):
    b = run.get("baseline")
    if not b:
        return {"status": "absent"}
    if b["final"] is None:  # did not fit / not scored; never a score of zero (D9)
        call = b.get("call") or {}
        return {"status": b.get("status"), "requested_tokens": call.get("requested_tokens"),
                "limit_tokens": call.get("limit_tokens"), "limit_kind": call.get("limit_kind")}
    key_values = {_norm(k["id"]): k.get("value") for k in run["items"]["key"]}
    universe = {_norm(i) for i in run["items"].get("universe") or []}
    score = _score(b["final"], key_values, universe)
    found = set(_ids(b["final"]))
    reached = reached_ids(run["items"].get("universe") or [], b.get("call"), b.get("status"))
    missed = [i for i in key_values if i not in found]
    unreached = [] if reached is None else [i for i in missed if i not in reached]
    # missed_unreached: misses after the point where the reply was cut off (information only, D17)
    return {"status": b.get("status"), "score": score, "missed": len(missed),
            "missed_unreached": len(unreached)}


def cross_check(s, b, run):
    """Of the swarm's assigned-but-missed items, how many the baseline also missed on this task.

    Separates "the model cannot do this line" from "the swarm lost it". None when the baseline
    was not scored (e.g. it did not fit in one call)."""
    missed = [p["id"] for p in s["per_item"] if p["bucket"] == "assigned_missed"]
    if "score" not in b:
        return {"assigned_missed": len(missed), "baseline_also_missed": None, "ids": None}
    base_ids = set(_ids(run["baseline"]["final"]))
    also = [i for i in missed if i not in base_ids]
    return {"assigned_missed": len(missed), "baseline_also_missed": len(also), "ids": also}


def autopsy(run):
    s, b = swarm_autopsy(run), baseline_autopsy(run)
    return {"run_id": run.get("run_id"), "swarm": s, "baseline": b,
            "cross": cross_check(s, b, run)}


# ---------- rendering ----------

def pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def render(run, a=None):
    """A plain-text full autopsy of one run."""
    a = a or autopsy(run)
    s, b = a["swarm"], a["baseline"]
    t = run.get("task", {})
    out = [f"# Autopsy: {run.get('run_id')}",
           f"task {t.get('task_id')}  size {t.get('size')}  seed {t.get('seed')}  "
           f"lines {t.get('n_lines')}  key items {s['key_count']}",
           f"model {run['config']['model']}  temperature {run['config']['temperature']}  "
           f"workers {run['config']['workers']}", ""]

    out.append("## Score")
    sc = s["score"]
    out.append(f"swarm:    recall {pct(sc['recall'])} ({sc['true_positives']}/{s['key_count']}), "
               f"precision {pct(sc['precision'])} ({sc['true_positives']}/{sc['final_count']}), "
               f"shortfall accurate {sc['value_accuracy']['accurate']}/{sc['value_accuracy']['found']}")
    if "score" in b:
        bs = b["score"]
        out.append(f"baseline: recall {pct(bs['recall'])} ({bs['true_positives']}/{s['key_count']}), "
                   f"precision {pct(bs['precision'])} ({bs['true_positives']}/{bs['final_count']}), "
                   f"shortfall accurate {bs['value_accuracy']['accurate']}/{bs['value_accuracy']['found']}"
                   + ("" if b["status"] == "ok" else f"  [{b['status']}]")
                   + (f"; {b['missed_unreached']} of its {b['missed']} misses came after its reply "
                      "was cut off" if b.get("missed_unreached") else ""))
    else:
        out.append(f"baseline: not scored ({b['status']}): requested {b.get('requested_tokens')} "
                   f"{b.get('limit_kind')} tokens, limit {b.get('limit_tokens')}")
    out.append("")

    out.append(f"## Where the {s['lost']} lost key items went")
    for bk in BUCKETS:
        out.append(f"{BUCKET_LABEL[bk]:<38} {s['buckets'][bk]}")
    out.append("")

    out.append("## The split")
    sw = run["swarm"]
    out.append(f"planner status {sw['planner'].get('status')}, briefs used "
               f"{sw['planner'].get('briefs_used')}")
    for n in sw["planner"].get("parse_notes", []):
        out.append(f"  note: {n}")
    for w in sw["workers"]:
        key_in = sum(1 for p in s["per_item"] if w["worker"] in p["in_slices"])
        found = sum(1 for p in s["per_item"] if w["worker"] in p["reported_by"])
        out.append(f"worker {w['worker']}: ranges {w['ranges']}  rows {len(w['slice'])}  "
                   f"key items in slice {key_in}  reported {len(w['reported'])} "
                   f"(of which key {found})  status {w.get('status')}")
        out.append(f"  brief: {w['brief'][:300]}")
        for n in w.get("parse_notes", []):
            out.append(f"  note: {n}")
    cov = s["coverage"]
    out.append(f"coverage: {cov['lines_unassigned']} of {cov['lines']} lines unassigned; "
               f"{cov['lines_in_2plus_slices']} lines in 2+ slices "
               f"({cov['key_lines_in_2plus_slices']} of them key items)")
    out.append("")

    out.append("## The merge")
    out.append(f"merger status {sw['merger'].get('status')}, final list {sc['final_count']} items "
               f"({sc['duplicates_in_final']} repeated ids removed)")
    fp = s["false_positives"]
    out.append(f"false positives kept from workers: {len(fp['worker_reported_kept'])}  "
               f"invented by merger: {len(fp['invented_by_merger'])}  "
               f"worker false positives the merger filtered out: {fp['worker_fps_filtered_by_merger']}")
    for kind, lst in (("kept from worker", fp["worker_reported_kept"]),
                      ("invented by merger", fp["invented_by_merger"])):
        for f in lst:
            out.append(f"  {kind}: {f['id']} ({f['kind'].replace('_', ' ')})")
    out.append("")

    out.append("## Every lost key item")
    base_ids = set(_ids(run["baseline"]["final"])) if "score" in b else None
    for p in s["per_item"]:
        if p["bucket"] != "kept":
            base = ("baseline not scored" if base_ids is None
                    else "baseline also missed" if p["id"] not in base_ids else "baseline found it")
            out.append(f"{p['id']}: {BUCKET_LABEL[p['bucket']]}; in slices of {p['in_slices'] or '-'}; "
                       f"reported by {p['reported_by'] or '-'}; {base}")
    c = a["cross"]
    if c["baseline_also_missed"] is not None:
        out.append(f"of {c['assigned_missed']} assigned-but-missed items, the baseline also missed "
                   f"{c['baseline_also_missed']}")
    if s["flags"] or s["notes"]:
        out.append("")
        out.append("## Flags")
        out += [f"- {f}" for f in s["flags"] + s["notes"]]
    return "\n".join(out)
