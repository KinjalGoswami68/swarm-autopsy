import json

import pytest

import agent
import autopsy
import ledger
import runfile
import swarm
from tests.test_swarm import CFG, FakeModel, even_plan


@pytest.fixture
def real_run(monkeypatch):
    task = ledger.generate("S", 2)
    monkeypatch.setattr(agent, "call_agent", FakeModel(task, even_plan(60), too_large={"baseline"}))
    return swarm.run_task(task, CFG)


def test_runner_output_is_valid(real_run):
    assert runfile.errors(real_run) == []


def test_save_load_roundtrip_and_autopsy(real_run, tmp_path):
    p = tmp_path / "runs" / "r.json"
    runfile.save(real_run, p)
    loaded = runfile.load(p)
    assert loaded == json.loads(json.dumps(real_run))
    assert autopsy.autopsy(loaded)["swarm"]["lost"] == 0
    assert not list(p.parent.glob("*.tmp"))


def test_invalid_rejected(real_run, tmp_path):
    bad = dict(real_run)
    del bad["items"]
    assert runfile.errors(bad)
    with pytest.raises(ValueError):
        runfile.save(bad, tmp_path / "x.json")


def test_bad_status_rejected(real_run):
    real_run["swarm"]["merger"]["status"] = "great"
    assert any("merger" in e for e in runfile.errors(real_run))
