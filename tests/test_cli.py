import agent
import cli
import ledger
from tests.test_swarm import FakeModel, even_plan


def test_run_table_autopsy_end_to_end(monkeypatch, tmp_path, capsys):
    def fake(model, temperature, prompt, call_id, **kw):
        size, seed = call_id[0].split("-")[1], int(call_id[0].split("s")[-1])
        task = ledger.generate(size, seed)
        too_large = {"baseline"} if size == "M" else set()
        return FakeModel(task, even_plan(task["n_lines"]), too_large=too_large)(
            model, temperature, prompt, call_id, **kw)
    monkeypatch.setattr(agent, "call_agent", fake)
    runs = tmp_path / "runs"
    cli.main(["run", "--sizes", "S", "M", "--seeds", "1", "2", "--itpm", "0", "--runs-dir", str(runs)])
    assert len(list(runs.glob("*.json"))) == 4
    cli.main(["run", "--sizes", "S", "--seeds", "1", "--itpm", "0", "--runs-dir", str(runs)])
    assert "skipped" in capsys.readouterr().out
    cli.main(["table", "--runs-dir", str(runs)])
    out = capsys.readouterr().out
    assert "| S | 4 | 1,2 | 12 | 0% (0/0) | n/a | 100% (100/100) | 100% (100/100) | 0.0 (0/0) | 0.0 (0/0) | 0.0 (0/0) | 0.0 (0/0) | 0 of 0 |" in out
    assert "n/a (no baseline)" in out
    assert "did not fit in one call†" in out and "Not a score of zero" in out
    cli.main(["autopsy", str(next(runs.glob("ledger-S-s1*.json")))])
    assert "# Autopsy" in capsys.readouterr().out


def test_rate_limit_exits_2(monkeypatch, tmp_path):
    def stop(*a, **k):
        raise agent.RateLimitStop("429")
    monkeypatch.setattr(agent, "call_agent", stop)
    try:
        cli.main(["run", "--sizes", "S", "--seeds", "1", "--itpm", "0", "--runs-dir", str(tmp_path)])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("expected exit 2")


def test_output_limit_rejection_is_not_reported_as_did_not_fit(monkeypatch, tmp_path, capsys):
    def fake(model, temperature, prompt, call_id, **kw):
        if call_id[1] == "baseline":
            raise agent.RequestTooLarge("Request too large on output tokens per minute (OTPM): "
                                        "Limit 1000, Requested 1342")
        task = ledger.generate("S", 1)
        return FakeModel(task, even_plan(60))(model, temperature, prompt, call_id, **kw)
    monkeypatch.setattr(agent, "call_agent", fake)
    cli.main(["run", "--sizes", "S", "--seeds", "1", "--itpm", "0", "--otpm", "0",
              "--runs-dir", str(tmp_path)])
    cli.main(["table", "--runs-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "did not fit" not in out and "not scored‡" in out and "output limit 1000" in out
