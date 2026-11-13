"""swarm-autopsy CLI: generate, run, autopsy, table."""
import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import agent
import autopsy
import ledger
import runfile
import swarm

RUNS_DIR = Path(__file__).parent / "runs"


def cmd_generate(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for size in args.sizes:
        for seed in args.seeds:
            t = ledger.generate(size, seed)
            p = out / f"{t['task_id']}.json"
            p.write_text(json.dumps(t, indent=1), encoding="utf-8")
            print(f"wrote {p}  ({t['n_lines']} lines, {t['n_planted']} planted)")


def cmd_run(args):
    if args.endpoint:
        agent.set_endpoint(args.endpoint)
    if args.max_tokens is None and args.otpm:
        args.max_tokens = args.otpm  # D15: expected output never exceeds the per-minute limit
    agent.PACER = agent.Pacer(itpm=args.itpm, otpm=args.otpm, out_reserve=args.max_tokens or 300)
    cfg = dict(model=args.model, temperature=args.temperature, reasoning_effort=args.reasoning_effort,
               workers=args.workers, max_tokens=args.max_tokens, itpm=args.itpm, otpm=args.otpm)
    runs_dir = Path(args.runs_dir)
    total = len(args.sizes) * len(args.seeds)
    done = 0
    for size in args.sizes:
        for seed in args.seeds:
            done += 1
            task = ledger.generate(size, seed)
            path = runs_dir / f"{swarm.run_id(task, cfg)}.json"
            if path.exists() and not args.force:
                print(f"[{done}/{total}] {path.name}: exists, skipped", flush=True)
                continue
            start = time.monotonic()
            print(f"[{done}/{total}] {task['task_id']}: running...", flush=True)
            try:
                run = swarm.run_task(task, cfg)
            except agent.RateLimitStop as e:
                print(f"STOPPED by rate limit: {e}\nRe-run the same command later; cached calls "
                      "are replayed and finished runs are skipped.", flush=True)
                sys.exit(2)
            runfile.save(run, path)
            a = autopsy.autopsy(run)
            s, b = a["swarm"], a["baseline"]
            calls = [run["swarm"]["planner"]["call"], *[w["call"] for w in run["swarm"]["workers"]],
                     run["swarm"]["merger"]["call"], run["baseline"]["call"]]
            cached = sum(1 for c in calls if c and c["cached"])
            base = (f"baseline recall {autopsy.pct(b['score']['recall'])}" if "score" in b
                    else f"baseline {b['status']}")
            print(f"[{done}/{total}] {path.name}: swarm recall {autopsy.pct(s['score']['recall'])}, "
                  f"lost {s['lost']} {s['buckets']}; {base}; "
                  f"{sum(1 for c in calls if c)} calls ({cached} cached), "
                  f"{time.monotonic() - start:.0f}s"
                  + (f"; flags: {s['flags']}" if s["flags"] else ""), flush=True)


def cmd_autopsy(args):
    run = runfile.load(args.run_file)
    if args.json:
        print(json.dumps(autopsy.autopsy(run), indent=1))
    else:
        print(autopsy.render(run))


def _fmt_mean(values, as_pct=False):
    vals = [v for v in values if v is not None]
    if not vals:
        return "n/a"
    m = statistics.mean(vals)
    each = "/".join(autopsy.pct(v)[:-1] if as_pct else str(v) for v in vals)
    return f"{autopsy.pct(m) if as_pct else f'{m:.1f}'} ({each})"


def _cross(crosses):
    if any(c["baseline_also_missed"] is None for c in crosses):
        return "n/a (no baseline)"
    also = sum(c["baseline_also_missed"] for c in crosses)
    total = sum(c["assigned_missed"] for c in crosses)
    return f"{also} of {total}"


def table(runs):
    """Markdown table: one row per (size, workers), means over seeds with per-seed values in brackets."""
    by_size = defaultdict(list)
    for run in runs:
        by_size[(run["task"]["size"], run["config"]["workers"])].append(run)
    rank = {s: i for i, s in enumerate(ledger.SIZES)}
    order = sorted(by_size, key=lambda k: (rank.get(k[0], 99), k[0], k[1]))
    lines = ["| size | W | seeds | K | baseline recall | baseline precision | swarm recall | "
             "swarm precision | lost: never assigned | lost: assigned, unreached (reply cut off) | "
             "lost: assigned, missed | assigned, missed: baseline also missed | "
             "lost: dropped at merge | swarm FPs kept-invented by merger, per seed |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    notes = []
    for key in order:
        size, workers = key
        rs = sorted(by_size[key], key=lambda r: r["task"]["seed"])
        aa = [autopsy.autopsy(r) for r in rs]
        base = [a["baseline"] for a in aa]
        if all("score" in b for b in base):
            b_rec = _fmt_mean([b["score"]["recall"] for b in base], True)
            b_pre = _fmt_mean([b["score"]["precision"] for b in base], True)
        else:
            unfit = [b for b in base if "score" not in b]
            sizes = sorted({b.get("requested_tokens") for b in unfit} - {None})
            if len(unfit) == len(base) and all(b.get("limit_kind") == "input" for b in unfit):
                b_rec = b_pre = "did not fit in one call†"
                notes.append(f"† size {size}: baseline not run to a score. The provider rejected "
                             f"the one-call prompt: requested {', '.join(map(str, sizes))} input "
                             f"tokens, limit {unfit[0].get('limit_tokens')} per request. "
                             "Not a score of zero.")
            else:
                b_rec = b_pre = "not scored‡"
                notes.append(f"‡ size {size}: baseline not scored in {len(unfit)} of {len(base)} "
                             "runs (see per-run notes). Not a score of zero.")
                for r, b in zip(rs, base):
                    if "score" not in b:
                        notes.append(f"* {r['task']['task_id']}: baseline {b['status']} "
                                     f"({b.get('limit_kind')} limit {b.get('limit_tokens')}, "
                                     f"requested {b.get('requested_tokens')})")
        sw = [a["swarm"] for a in aa]
        lines.append("| " + " | ".join([
            size, str(workers), ",".join(str(r["task"]["seed"]) for r in rs),
            str(sw[0]["key_count"]), b_rec, b_pre,
            _fmt_mean([s["score"]["recall"] for s in sw], True),
            _fmt_mean([s["score"]["precision"] for s in sw], True),
            _fmt_mean([s["buckets"]["never_assigned"] for s in sw]),
            _fmt_mean([s["buckets"]["assigned_unreached"] for s in sw]),
            _fmt_mean([s["buckets"]["assigned_missed"] for s in sw]),
            _cross([a["cross"] for a in aa]),
            _fmt_mean([s["buckets"]["dropped_at_merge"] for s in sw]),
            "/".join(f"{len(s['false_positives']['worker_reported_kept'])}-"
                     f"{len(s['false_positives']['invented_by_merger'])}" for s in sw),
        ]) + " |")
        for r, a in zip(rs, aa):
            for f in a["swarm"]["flags"]:
                notes.append(f"* {r['task']['task_id']}: {f}")
            if a["baseline"].get("status") not in ("ok", "rejected_too_large"):
                extra = (f" ({a['baseline']['missed_unreached']} of its {a['baseline']['missed']} "
                         "misses came after the cut)" if a["baseline"].get("missed_unreached") else "")
                notes.append(f"* {r['task']['task_id']}: baseline {a['baseline']['status']}{extra}")
    return "\n".join(lines + ([""] + notes if notes else []))


def cmd_table(args):
    runs = [runfile.load(p) for p in sorted(Path(args.runs_dir).glob("*.json"))]
    if args.model:
        runs = [r for r in runs if r["config"]["model"] == args.model]
    if not runs:
        print("no run files found")
        return
    print(table(runs))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="swarm-autopsy")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="write ledger tasks (with answer keys) to disk")
    g.add_argument("--sizes", nargs="+", default=list(ledger.SIZES), choices=list(ledger.SIZES))
    g.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    g.add_argument("--out", default="tasks")
    g.set_defaults(func=cmd_generate)

    r = sub.add_parser("run", help="run swarm and baseline; one run file per task")
    r.add_argument("--sizes", nargs="+", default=list(ledger.SIZES), choices=list(ledger.SIZES))
    r.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--model", default=agent.DEFAULT_MODEL)
    r.add_argument("--endpoint", default=None, help="OpenAI-compatible base URL (default Groq)")
    r.add_argument("--temperature", type=float, default=0.0)
    r.add_argument("--reasoning-effort", default=None)
    r.add_argument("--max-tokens", type=int, default=None)
    r.add_argument("--itpm", type=int, default=7000, help="input tokens/minute to pace to (0 = off)")
    r.add_argument("--otpm", type=int, default=1000, help="output tokens/minute to pace to (0 = off)")
    r.add_argument("--runs-dir", default=str(RUNS_DIR))
    r.add_argument("--force", action="store_true", help="rewrite existing run files")
    r.set_defaults(func=cmd_run)

    a = sub.add_parser("autopsy", help="full autopsy of one run file")
    a.add_argument("run_file")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_autopsy)

    t = sub.add_parser("table", help="summary table over run files")
    t.add_argument("--runs-dir", default=str(RUNS_DIR))
    t.add_argument("--model", default=None)
    t.set_defaults(func=cmd_table)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
