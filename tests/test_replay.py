import json

import pytest

import agent
import autopsy
import cli
import ledger2
import replay
import runfile
from tests.test_ledger2 import CtxModel


class ReplayModel(CtxModel):
    """CtxModel, but also answers replay call ids [task, "replay", label, role, ...]."""

    def __init__(self, task):
        super().__init__(task)
        self.calls = []

    def __call__(self, model, temperature, prompt, call_id, **kw):
        self.calls.append((call_id, prompt))
        if call_id[1] == "replay":
            call_id = [call_id[0], call_id[3], *call_id[4:]]
        return super().__call__(model, temperature, prompt, call_id, **kw)


@pytest.fixture
def stored(monkeypatch, tmp_path):
    task = ledger2.generate("S", 1)
    fake = ReplayModel(task)
    monkeypatch.setattr(agent, "call_agent", fake)
    monkeypatch.setattr(replay, "REPLAY_DIR", tmp_path / "replays")
    cli.main(["run", "--family", "ledger-ctx", "--sizes", "S", "--seeds", "1", "--runs-dir", str(tmp_path)])
    path = next(tmp_path.glob("ledgerctx-*.json"))
    fake.calls.clear()
    return path, fake, task


def test_r1_adds_table_to_every_slice_keeps_briefs(stored):
    path, fake, task = stored
    run = runfile.load(path)
    rec = replay.replay(run, "R1")
    for w0, w in zip(run["swarm"]["workers"], rec["swarm"]["workers"]):
        assert w["brief"] == w0["brief"]
        assert all(f"RATE:{r['rate_code']}" in w["slice"] for r in task["rate_rows"])
        assert set(w0["slice"]) <= set(w["slice"])
    assert rec["replay"]["of"] == run["run_id"] and rec["run_id"].endswith("__R1")
    assert rec["baseline"] == run["baseline"]


def test_identical_prompt_reuses_original(stored):
    path, fake, task = stored
    run = runfile.load(path)
    rec = replay.replay(run, "R1")
    w1 = rec["swarm"]["workers"][0]  # rows 1-17 already include the table
    assert w1["reused_from_original"] is True
    assert all(c[0][4] != 1 for c in fake.calls if c[0][3] == "worker")  # no call for worker 1
    assert rec["swarm"]["workers"][1]["reused_from_original"] is False


def test_r2_neutral_briefs_same_slices(stored):
    path, fake, task = stored
    run = runfile.load(path)
    rec = replay.replay(run, "R2")
    for w0, w in zip(run["swarm"]["workers"], rec["swarm"]["workers"]):
        assert w["brief"] == replay.NEUTRAL_BRIEF and w["slice"] == w0["slice"]


def test_r3_both(stored):
    path, fake, task = stored
    rec = replay.replay(runfile.load(path), "R3")
    assert all(w["brief"] == replay.NEUTRAL_BRIEF and "RATE:" + task["rate_rows"][0]["rate_code"] in w["slice"]
               for w in rec["swarm"]["workers"])


def test_r4_planner_prompt_is_frozen_plus_one_sentence(stored):
    path, fake, task = stored
    rec = replay.replay(runfile.load(path), "R4")
    planner_calls = [p for cid, p in fake.calls if cid[3] == "planner"]
    assert len(planner_calls) == 1
    frozen = ledger2.planner_prompt(task, 4)
    assert planner_calls[0] == frozen.replace(replay._ANCHOR, replay._ANCHOR + " " + replay.TRUTH_SENTENCE)
    assert len(planner_calls[0]) - len(frozen) == len(replay.TRUTH_SENTENCE) + 1
    assert rec["swarm"]["planner"].get("reused_from_original") is None


def test_original_file_never_changes_and_table(stored, capsys):
    path, fake, task = stored
    before = path.read_bytes()
    cli.main(["replay", str(path), "--tpm", "0"])
    assert path.read_bytes() == before
    assert len(list(replay.REPLAY_DIR.glob("*.json"))) == 4
    cli.main(["replay", str(path), "--tpm", "0"])
    assert capsys.readouterr().out.count("exists, skipped") == 4
    cli.main(["replay-table", str(path)])
    out = capsys.readouterr().out
    assert "No merge replay" in out and ledger2.FIXED_SENTENCE in out
    assert out.count("| S s1 W=4 |") == 5
    rec = runfile.load(next(replay.REPLAY_DIR.glob("*__R1.json")))
    assert autopsy.swarm_autopsy(rec)["key_count"] == 12


# ---------- D37: planner guidance replays (R5 = Acyclic's delegation text) ----------

def test_protocol_file_is_byte_identical_to_source_blob():
    g = replay.r5_guidance()
    assert g["git_blob"] == "d9b9a8fa1d4325572ab1cb933b1e0320392cfef3" and g["bytes"] == 497


def test_r5_planner_prompt_is_frozen_plus_guidance(stored, monkeypatch, tmp_path):
    path, fake, task = stored
    monkeypatch.setattr(replay, "GUIDANCE_DIR", tmp_path / "guidance")
    g = replay.r5_guidance()
    rec = replay.replay(runfile.load(path), "R5", g)
    planner_calls = [p for cid, p in fake.calls if cid[3] == "planner"]
    assert len(planner_calls) == 1
    assert planner_calls[0] == ledger2.planner_prompt(task, 4) + "\n\nDelegation guidance:\n" + g["text"]
    assert rec["replay"]["label"] == "R5" and rec["replay"]["guidance"]["git_blob"] == g["git_blob"]
    assert rec["run_id"].endswith("__R5")
    assert replay.path_for(rec, "R5", g).parent == tmp_path / "guidance"


def test_guidance_replay_applies_reuse_rule(stored):
    path, fake, task = stored
    rec = replay.replay(runfile.load(path), "R5", replay.r5_guidance())
    # the fake planner returns the same even split, so every worker prompt and the merger prompt
    # are byte-identical to the original's and are reused (D29), not re-called
    assert all(w["reused_from_original"] for w in rec["swarm"]["workers"])
    assert rec["swarm"]["merger"]["reused_from_original"] is True
    assert [cid[3] for cid, _ in fake.calls] == ["planner"]


def test_custom_guidance_file_label_and_cli(stored, monkeypatch, tmp_path, capsys):
    path, fake, task = stored
    monkeypatch.setattr(replay, "GUIDANCE_DIR", tmp_path / "guidance")
    gfile = tmp_path / "my-guidance.md"
    gfile.write_bytes(b"Give each worker every row it needs.\n")
    g = replay.load_guidance(gfile)
    assert g["label"] == "G-" + replay.git_blob_sha(b"Give each worker every row it needs.\n")[:8]
    cli.main(["replay", str(path), "--replays", "--planner-guidance", str(gfile), "--tpm", "0"])
    out = list((tmp_path / "guidance").glob("*.json"))
    assert len(out) == 1 and out[0].name.endswith(f"__{g['label']}.json")
    assert runfile.load(out[0])["replay"]["guidance"]["text"] == "Give each worker every row it needs.\n"


def test_guidance_replays_are_not_published():
    import build_site
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        m = build_site.build(Path(d) / "_site")
    assert not any("guidance" in p for p in m["runs"] + m["replays"])
