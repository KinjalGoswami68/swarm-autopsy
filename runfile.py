"""Load, validate and save run files (schema/run.schema.json, described in SCHEMA.md)."""
import json
import os
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema" / "run.schema.json"
_validator = None


def validator():
    global _validator
    if _validator is None:
        from jsonschema import Draft202012Validator
        _validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    return _validator


def errors(run):
    """List of human-readable schema errors; empty means valid."""
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
            for e in sorted(validator().iter_errors(run), key=lambda e: list(e.path))]


def load(path):
    run = json.loads(Path(path).read_text(encoding="utf-8"))
    errs = errors(run)
    if errs:
        raise ValueError(f"{path} is not a valid run file:\n  " + "\n  ".join(errs[:10]))
    return run


def save(run, path):
    errs = errors(run)
    if errs:
        raise ValueError("refusing to save an invalid run file:\n  " + "\n  ".join(errs[:10]))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
