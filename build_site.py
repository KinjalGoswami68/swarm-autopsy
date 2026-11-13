"""Assemble the static site into _site/ (what GitHub Pages publishes).

Copies site/, the run files (runs/*.json, runs/replays/*.json) and schema/, and writes
manifest.json: the list of run-file paths, nothing else. Every number the site shows is computed in
the browser from those run files (SITE_RULES.md), so the manifest carries no figures.

    python build_site.py          # build into _site/
    python build_site.py --serve  # build, then serve on http://127.0.0.1:8000 (needs node)
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "_site"


def build(out=OUT):
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    (out / "runs" / "replays").mkdir(parents=True)
    runs = sorted((ROOT / "runs").glob("*.json"))
    replays = sorted((ROOT / "runs" / "replays").glob("*.json"))
    for p in runs:
        shutil.copy2(p, out / "runs" / p.name)
    for p in replays:
        shutil.copy2(p, out / "runs" / "replays" / p.name)
    shutil.copytree(ROOT / "schema", out / "schema")
    manifest = {"runs": [f"runs/{p.name}" for p in runs],
                "replays": [f"runs/replays/{p.name}" for p in replays]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as they are
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    m = build()
    print(f"built {OUT}: {len(m['runs'])} runs, {len(m['replays'])} replays")
    if args.serve:  # Node server: Python's http.server reset connections mid-file on Windows
        import subprocess
        subprocess.run(["node", str(ROOT / "tools" / "serve.mjs"), str(OUT), str(args.port)])


if __name__ == "__main__":
    main()
