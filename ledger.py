"""Seeded, offline task generator: a remittance ledger with planted underpayments."""
import random

SIZES = {"S": (60, 12), "M": (200, 24), "L": (600, 48)}  # size -> (lines N, planted K)
COLUMNS = ["row", "line_id", "payer", "service_code", "qty", "unit_rate", "paid"]
PAYERS = ["Northgate Mutual", "Kestrel Health", "Arbor Benefit Co", "Lumen Assurance",
          "Pinecrest Plan", "Harbor Union Fund", "Silverline Care", "Meridian Cover"]
ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I

TASK_TEXT = (
    "You are auditing a remittance ledger. Each line is one billed service. "
    "The amount owed for a line is qty x unit_rate. A line is UNDERPAID when paid is less than "
    "qty x unit_rate; its shortfall is (qty x unit_rate) - paid, in currency units with two decimals. "
    "Lines paid exactly, or overpaid, are not underpayments and must not be reported. "
    "Find every underpaid line."
)


def task_id(size, seed):
    return f"ledger-{size}-s{seed}"


def _line_ids(rng, n):
    ids = set()
    while len(ids) < n:
        ids.add("RX-" + "".join(rng.choice(ID_ALPHABET) for _ in range(5)))
    out = sorted(ids)
    rng.shuffle(out)
    return out


def _deviation(rng, expected):
    """A shortfall/overpayment in cents: 1%-35% of the expected amount, at least 0.37, never round."""
    cents = int(expected * rng.uniform(0.01, 0.35))
    cents = max(cents, 37)
    if cents % 100 == 0:
        cents += rng.randint(1, 99)
    return min(cents, expected - 1)


def generate(size, seed):
    """Return a task dict. key = planted underpayments, sorted by row. Deterministic in (size, seed)."""
    n, k = SIZES[size]
    rng = random.Random(f"{size}:{seed}")
    ids = _line_ids(rng, n)
    positions = list(range(n))
    rng.shuffle(positions)
    planted = set(positions[:k])
    overpaid = set(positions[k:2 * k])
    rows, key = [], []
    for i in range(n):
        qty = rng.randint(1, 40)
        rate = rng.randint(1250, 48000)  # cents: 12.50 .. 480.00
        expected = qty * rate
        paid = expected
        if i in planted:
            short = _deviation(rng, expected)
            paid = expected - short
            key.append({"line_id": ids[i], "row": i + 1, "shortfall_cents": short})
        elif i in overpaid:
            paid = expected + _deviation(rng, expected)
        rows.append({"row": i + 1, "line_id": ids[i], "payer": rng.choice(PAYERS),
                     "service_code": f"SVC-{rng.randint(100, 999)}", "qty": qty,
                     "unit_rate_cents": rate, "paid_cents": paid})
    return {"family": "remittance-ledger", "task_id": task_id(size, seed), "size": size,
            "seed": seed, "n_lines": n, "n_planted": k, "n_overpaid": k,
            "rows": rows, "key": key}


def money(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def header():
    return " | ".join(COLUMNS)


def render_rows(rows):
    """Text table for a prompt. Same columns and number format for every row: no planted marker."""
    lines = [header()]
    for r in rows:
        lines.append(" | ".join([str(r["row"]), r["line_id"], r["payer"], r["service_code"],
                                 str(r["qty"]), money(r["unit_rate_cents"]), money(r["paid_cents"])]))
    return "\n".join(lines)


def rows_in_ranges(rows, ranges):
    """Rows whose 1-based `row` falls in any [start, end] range (inclusive), in ledger order."""
    return [r for r in rows if any(a <= r["row"] <= b for a, b in ranges)]
