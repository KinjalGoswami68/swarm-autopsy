"""The site's autopsy.js must give exactly what autopsy.py gives, on every committed run file."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import autopsy

ROOT = Path(__file__).parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def run_js(paths, pct_cases=None):
    env = dict(os.environ)
    if pct_cases is not None:
        env["PCT_CASES"] = json.dumps(pct_cases)
    out = subprocess.run([NODE, str(ROOT / "tests" / "parity_runner.mjs"), *map(str, paths)],
                         capture_output=True, text=True, encoding="utf-8", check=True, env=env)
    return json.loads(out.stdout)


def committed_runs():
    return sorted((ROOT / "runs").glob("*.json")) + sorted((ROOT / "runs" / "replays").glob("*.json"))


def test_every_committed_run_file_matches():
    paths = committed_runs()
    assert len(paths) >= 20
    js = run_js(paths)
    for p in paths:
        py = autopsy.autopsy(json.loads(p.read_text(encoding="utf-8")))
        assert js[str(p)] == json.loads(json.dumps(py)), p.name


def test_edge_case_runs_match(tmp_path):
    from tests.test_autopsy import make_run, _truncate
    from tests.test_ledger2 import ctx_run, KEY
    cases = {
        "buckets": make_run([(["B", "C", "E"], ["C"]), (["D", "F"], ["D"])], final=["D", "ZZ", "E", "D"]),
        "empty_final": make_run([(["A"], [])], final=[]),
        "planner_failed": make_run([], final=[]),
        "baseline_unscored": make_run([(["A"], ["A"])], final=["A"], baseline_final=None,
                                      baseline_status="rejected_too_large"),
        "ctx_all": ctx_run([(["A", "B"], []), (["RATE:R1", "RATE:R2", "C", "D", "E", "F"], ["E"])],
                           final=["PAIR:B+D", "PAIR:D+E", "PAIR:A+C", "G"], key=KEY),
    }
    trunc = make_run([(["A", "B", "C", "D"], [])], final=[])
    _truncate(trunc, 0, '[{"line_id":"A","shortfall":0},{"line_id":"B","sh')
    trunc["baseline"]["status"] = "truncated"
    trunc["baseline"]["call"] = {"raw_text": '[{"line_id":"A","shortfall":1},{"line_id":"B","sh'}
    trunc["baseline"]["final"] = [{"id": "A", "value": 1}]
    cases["truncated"] = trunc
    cases["planner_failed"]["swarm"]["planner"]["status"] = None
    cases["planner_failed"]["swarm"]["merger"]["status"] = "not_called"
    paths = []
    for name, run in cases.items():
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(run), encoding="utf-8")
        paths.append(p)
    js = run_js(paths)
    for name, p in zip(cases, paths):
        assert js[str(p)] == json.loads(json.dumps(autopsy.autopsy(cases[name]))), name


def test_pct_rounds_like_python():
    cases = [0, 1, 0.125, 0.375, 1 / 3, 2 / 3, 0.005, 0.995, 0.5, 0.083333, None]
    js = run_js([], pct_cases=cases)["__pct__"]
    assert js == [autopsy.pct(x) for x in cases]
