"""Model-read brief annotations (DECISIONS D27). They never change a bucket or a score.

For each worker brief, one cached judge call at temperature 0 answers:
  a) does the brief rely on something the worker was not given (another worker's output, or
     ledger rows outside its slice)?
  b) does the brief limit the worker to only some kinds of finding?
each with the exact sentence quoted as evidence. Quotes are checked against the brief text.
"""
import json
import re

import agent
import swarm

JUDGE_VERSION = 1
NOTE = ("Model-read annotations (D27): a judge model's reading of each brief. "
        "They never change a bucket or a score.")


def _structure(run):
    t = run["task"]
    if t.get("family") == "ledger-ctx":
        return (f"Ledger: rows 1 to {t['n_rate_codes']} are the rate table; rows "
                f"{t['n_rate_codes'] + 1} to {t['n_rows']} are line items.",
                "underpaid lines and duplicated claims (a claim_id on more than one line item)",
                ["underpaid", "duplicates"], t["n_rate_codes"])
    return (f"Ledger: rows 1 to {t['n_lines']} are line items.", "underpaid lines",
            ["underpaid"], 0)


def judge_prompt(run, worker):
    structure, kinds_text, kinds, n_rate = _structure(run)
    ranges = worker["ranges"]
    rows = ", ".join(f"{a} to {b}" for a, b in ranges) or "none"
    if n_rate:
        has_table = any(a <= n_rate for a, b in ranges)
        table = (f"These rows {'include' if has_table else 'do not include'} the rate table "
                 f"(rows 1 to {n_rate}).")
    else:
        table = ""
    return (
        'You are checking one instruction ("brief") that a planner wrote for a worker in a '
        "multi-agent audit of a ledger.\n\n"
        "Facts about the worker (these are certain):\n"
        "- The worker receives only this brief and the ledger rows listed below. It cannot see the "
        "task description, the other workers, their briefs or their outputs.\n"
        f"- {structure}\n"
        f"- Rows given to this worker: {rows}. {table}\n"
        f"- The overall task has these kinds of finding: {kinds_text}.\n\n"
        f"Brief:\n<<<\n{worker['brief']}\n>>>\n\n"
        "Answer two questions.\n"
        "a) Does the brief rely on something the worker was not given: another worker's output, "
        "or ledger rows outside the rows listed above?\n"
        "b) Does the brief limit the worker to only some of the kinds of finding listed above "
        "(or to none of them)?\n"
        'For each, answer "yes" or "no" and quote the exact sentence from the brief that is your '
        'evidence, copied character for character. Use "" when the answer is no and no sentence is '
        "relevant. For b, also list the kinds of finding the brief asks for.\n"
        "Reply with only a JSON object:\n"
        '{"a": {"answer": "yes or no", "quote": "..."}, '
        f'"b": {{"answer": "yes or no", "quote": "...", "kinds": {json.dumps(kinds)}}}}}'
    )


_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_QUOTES = {ord("‘"): "'", ord("’"): "'", ord("“"): '"', ord("”"): '"'}


def _canon(text):
    text = (text or "").translate(_DASHES).translate(_QUOTES).replace("×", "x")
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_verified(quote, brief):
    """True when the quote appears in the brief (ignoring whitespace, case, dash and quote style)."""
    q = _canon(quote)
    return bool(q) and q.rstrip(".") in _canon(brief)


def parse_judgement(text, brief, all_kinds=None):
    """D28: answer b is derived from the judge's own `kinds` list (yes when it lists fewer kinds
    than the task has); the judge's yes/no is kept as `judge_answer`. Falls back to the yes/no
    when the list is missing or unusable."""
    data = agent.extract_json(text)
    out = {}
    for q in ("a", "b"):
        part = data.get(q) if isinstance(data, dict) else None
        if not isinstance(part, dict) or str(part.get("answer", "")).strip().lower() not in ("yes", "no"):
            out[q] = {"answer": None, "quote": None, "quote_verified": False}
            continue
        quote = part.get("quote") if isinstance(part.get("quote"), str) else ""
        entry = {"answer": part["answer"].strip().lower(), "quote": quote,
                 "quote_verified": quote_verified(quote, brief)}
        if q == "b":
            kinds = part.get("kinds")
            entry["kinds"] = kinds if isinstance(kinds, list) else None
            entry["judge_answer"] = entry["answer"]
            if all_kinds and isinstance(kinds, list) and all(isinstance(k, str) for k in kinds):
                listed = {k.strip().lower() for k in kinds} & set(all_kinds)
                entry["answer"] = "yes" if listed != set(all_kinds) else "no"
                entry["derived_from_kinds"] = True
        out[q] = entry
    return out


def annotate(run, cfg):
    """Return the run with run["annotations"] filled; one cached judge call per brief."""
    briefs = []
    for w in run["swarm"]["workers"]:
        prompt = judge_prompt(run, w)
        r = agent.call_agent(cfg["model"], cfg["temperature"], prompt,
                             ["judge", JUDGE_VERSION, run["run_id"], w["worker"]],
                             reasoning_effort=cfg.get("reasoning_effort"),
                             max_tokens=swarm.max_tokens_for(cfg, prompt))
        j = parse_judgement(r["raw_text"], w["brief"], _structure(run)[2]) if r["raw_text"] else {
            "a": {"answer": None, "quote": None, "quote_verified": False},
            "b": {"answer": None, "quote": None, "quote_verified": False, "kinds": None}}
        briefs.append({"worker": w["worker"],
                       "relies_on_missing": j["a"], "limits_kinds": j["b"],
                       "raw_text": r["raw_text"], "error": r["error"],
                       "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"],
                       "cached": r["cached"]})
    run["annotations"] = {"note": NOTE, "judge_version": JUDGE_VERSION,
                          "judge": {"model": cfg["model"], "endpoint": agent.ENDPOINT,
                                    "temperature": cfg["temperature"],
                                    "reasoning_effort": cfg.get("reasoning_effort")},
                          "briefs": briefs}
    return run


def rederive(run):
    """Re-parse stored judge replies with the current rules (no model calls)."""
    kinds = _structure(run)[2]
    briefs = {w["worker"]: w["brief"] for w in run["swarm"]["workers"]}
    for b in (run.get("annotations") or {}).get("briefs") or []:
        if b.get("raw_text"):
            j = parse_judgement(b["raw_text"], briefs[b["worker"]], kinds)
            b["relies_on_missing"], b["limits_kinds"] = j["a"], j["b"]
    if run.get("annotations"):
        run["annotations"]["b_rule"] = "derived from the judge's kinds list (D28)"
    return run


def summary(run):
    """{worker: (a, b)} with 'yes'/'no'/None, for tables and renders."""
    ann = (run.get("annotations") or {}).get("briefs") or []
    return {b["worker"]: (b["relies_on_missing"]["answer"], b["limits_kinds"]["answer"]) for b in ann}
