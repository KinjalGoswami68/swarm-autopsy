"""site/js/validate.js must accept and reject the same run files as Python's jsonschema (D30)."""
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import runfile

ROOT = Path(__file__).parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def js_errors(paths):
    out = subprocess.run([NODE, str(ROOT / "tests" / "validate_runner.mjs"), *map(str, paths)],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def mutations(run):
    """Invalid variants, each breaking a different keyword the schema uses."""
    def m(fn):
        r = copy.deepcopy(run); fn(r); return r
    return {
        "missing_items": m(lambda r: r.pop("items")),
        "bad_version": m(lambda r: r.update(schema_version=3)),
        "bad_status": m(lambda r: r["swarm"]["merger"].update(status="great")),
        "workers_zero": m(lambda r: r["config"].update(workers=0)),
        "item_id_empty": m(lambda r: r["items"]["key"][0].update(id="")),
        "value_float": m(lambda r: r["items"]["key"][0].update(value=1.5)),
        "range_three": m(lambda r: r["swarm"]["workers"][0].update(ranges=[[1, 2, 3]])),
        "slice_not_list": m(lambda r: r["swarm"]["workers"][0].update(slice="rows 1-10")),
        "final_wrong": m(lambda r: r["baseline"].update(final="none")),
        "needs_empty": m(lambda r: r["items"]["key"][0].update(needs=[])),
        "temperature_text": m(lambda r: r["config"].update(temperature="0")),
    }


def test_validity_matches_jsonschema(tmp_path):
    runs = sorted((ROOT / "runs").glob("*.json")) + sorted((ROOT / "runs" / "replays").glob("*.json"))
    base = json.loads((ROOT / "runs" / "ledgerctx-S-s1__openai_gpt-oss-120b__w4__t0.0.json").read_text(encoding="utf-8"))
    paths = list(runs)
    for name, bad in mutations(base).items():
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        paths.append(p)
    js = js_errors(paths)
    for p in paths:
        py = runfile.errors(json.loads(Path(p).read_text(encoding="utf-8")))
        assert bool(js[str(p)]) == bool(py), (Path(p).name, js[str(p)], py)
    assert all(js[str(p)] == [] for p in runs)
    assert all(js[str(p)] for p in paths[len(runs):])


def test_unsupported_keyword_is_refused(tmp_path):
    script = tmp_path / "t.mjs"
    script.write_text(
        f'import {{ validate }} from "{(ROOT / "site" / "js" / "validate.js").as_uri()}";\n'
        'try { validate({type: "object", patternProperties: {}}, {}); console.log("accepted"); }\n'
        'catch (e) { console.log("refused: " + e.message); }\n', encoding="utf-8")
    out = subprocess.run([NODE, str(script)], capture_output=True, text=True, check=True).stdout
    assert out.startswith("refused") and "patternProperties" in out
