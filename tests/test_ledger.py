import pytest

import ledger


@pytest.mark.parametrize("size", ["S", "M", "L"])
def test_counts_and_key_consistency(size):
    t = ledger.generate(size, 1)
    n, k = ledger.SIZES[size]
    assert len(t["rows"]) == n and len(t["key"]) == k
    by_id = {r["line_id"]: r for r in t["rows"]}
    under = [r for r in t["rows"] if r["paid_cents"] < r["qty"] * r["unit_rate_cents"]]
    over = [r for r in t["rows"] if r["paid_cents"] > r["qty"] * r["unit_rate_cents"]]
    assert len(under) == k and len(over) == k
    assert {r["line_id"] for r in under} == {item["line_id"] for item in t["key"]}
    for item in t["key"]:
        r = by_id[item["line_id"]]
        assert item["shortfall_cents"] == r["qty"] * r["unit_rate_cents"] - r["paid_cents"] > 0
        assert item["row"] == r["row"]


def test_deterministic_per_seed():
    assert ledger.generate("M", 3) == ledger.generate("M", 3)
    assert ledger.generate("M", 3)["key"] != ledger.generate("M", 4)["key"]


def test_ids_unique_and_unguessable():
    t = ledger.generate("L", 2)
    ids = [r["line_id"] for r in t["rows"]]
    assert len(set(ids)) == len(ids)
    assert ids != sorted(ids)  # not sequential in row order


def test_render_has_no_planted_marker():
    t = ledger.generate("S", 1)
    text = ledger.render_rows(t["rows"])
    for word in ["planted", "underpaid", "shortfall", "key", "flag"]:
        assert word not in text.lower()
    lines = text.splitlines()
    assert lines[0] == ledger.header()
    assert len(lines) == 61
    assert all(len(line.split(",")) == len(ledger.COLUMNS) for line in lines)


def test_no_round_deviations():
    for seed in range(5):
        t = ledger.generate("M", seed)
        assert all(item["shortfall_cents"] % 100 != 0 for item in t["key"])


def test_money_format():
    assert ledger.money(5) == "0.05" and ledger.money(123456) == "1234.56"


def test_rows_in_ranges():
    t = ledger.generate("S", 1)
    got = ledger.rows_in_ranges(t["rows"], [[1, 3], [10, 10], [2, 4]])
    assert [r["row"] for r in got] == [1, 2, 3, 4, 10]
