"""Assemble the static site into _site/ (what GitHub Pages publishes).

Copies site/, the run files (runs/*.json, runs/replays/*.json, and since D38 the guidance replays
runs/guidance/*.json with their annotation sidecars), schema/ and protocol/ (the R5 guidance text,
its provenance and Apache-2.0 licence files), and writes manifest.json: the list of run-file paths,
nothing else. Every number the site shows is computed in
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
    groups = {"runs": "runs", "replays": "runs/replays", "guidance": "runs/guidance",
              "annotations": "runs/guidance/annotations"}
    manifest = {}
    for key, rel in groups.items():
        files = sorted((ROOT / rel).glob("*.json"))
        (out / rel).mkdir(parents=True, exist_ok=True)
        for p in files:
            shutil.copy2(p, out / rel / p.name)
        manifest[key] = [f"{rel}/{p.name}" for p in files]
    shutil.copytree(ROOT / "schema", out / "schema")
    shutil.copytree(ROOT / "protocol", out / "protocol")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as they are
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    m = build()
    print(f"built {OUT}: {len(m['runs'])} runs, {len(m['replays'])} replays, "
          f"{len(m['guidance'])} guidance replays, {len(m['annotations'])} annotation sidecars")
    if args.serve:  # Node server: Python's http.server reset connections mid-file on Windows
        import subprocess
        subprocess.run(["node", str(ROOT / "tools" / "serve.mjs"), str(OUT), str(args.port)])


if __name__ == "__main__":
    main()
