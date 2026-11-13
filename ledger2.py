"""Task family 2, "ledger-ctx": a ledger built so that splitting can hurt (DECISIONS D22).

Rows 1..T are a rate table. Rows T+1..T+N are line items; about half give their own unit_rate,
the rest give a rate_code defined in the table. Planted items:
  line     underpaid row with an inline unit_rate            needs: its row
  context  underpaid row with only a rate_code               needs: its row + that code's table row
  pair     one claim_id billed on two rows (far or near)     needs: both rows
Seeded and offline; the key is never in any prompt.
"""
import json
import random
import re

import agent

FAMILY = "ledger-ctx"
# size -> (line items N, rate codes T, line, context, far pairs, near pairs)   (D22: owner-approved)
SIZES = {"S": (60, 10, 4, 4, 3, 1), "M": (200, 20, 8, 8, 6, 2), "L": (600, 40, 16, 16, 12, 4)}
RATE_COLUMNS = ["row", "rate_code", "unit_rate"]
LINE_COLUMNS = ["row", "line_id", "claim_id", "qty", "unit_rate", "rate_code", "paid"]
ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
NEAR_MAX = 5  # near pair: rows at most this far apart

FIXED_SENTENCE = ("This family is built so that splitting can hurt; its numbers show the autopsy "
                  "detects split and context failures, not how often swarms lose in general.")

ANSWER_ONLY = "Do not show your working or any explanation."

# ---------------- frozen prompt text (D22: never adjusted after seeing results) ----------------
TASK_TEXT = (
    "You are auditing a remittance ledger with two sections. The rate table lists rate codes and "
    "their unit rates. Each line item is one billed service; it gives either its own unit_rate or a "
    "rate_code whose unit rate is in the rate table. The amount owed for a line is qty x unit rate. "
    "A line is UNDERPAID when paid is less than the amount owed; its shortfall is "
    "(amount owed) - paid, in currency units with two decimals. Lines paid exactly, or overpaid, are "
    "not underpayments and must not be reported as underpaid. A claim is DUPLICATED when the same "
    "claim_id appears on more than one line item (billed more than once). "
    "Find every underpaid line and every duplicated claim."
)

ITEM_FORMAT = (
    ANSWER_ONLY + ' Reply with only a JSON object: {"underpaid": [{"line_id": "<line_id>", '
    '"shortfall": <amount with two decimals>}], "duplicates": [{"line_ids": ["<line_id>", '
    '"<line_id>"]}]}. List only lines whose shortfall is greater than 0. '
    'Use empty lists if there are none.'
)


def structure_text(task):
    """What the planner is told about the ledger: sections and headers, never contents (D22)."""
    t, n = task["n_rate_codes"], task["n_lines"]
    return (
        f"The ledger has {t + n} rows. Rows 1 to {t} are the rate table, with columns:\n"
        f"{','.join(RATE_COLUMNS)}\n"
        f"Rows {t + 1} to {t + n} are line items, with columns:\n"
        f"{','.join(LINE_COLUMNS)}\n"
        "A line item gives either its own unit_rate or a rate_code defined in the rate table. "
        "A claim_id may appear on more than one line item.\n"
        "You will not see the rows themselves."
    )


def planner_prompt(task, workers):
    return (
        f"{TASK_TEXT}\n\n{structure_text(task)}\n\n"
        f"You coordinate {workers} workers. Each worker receives only the brief you write for it and "
        "the ledger rows you assign to it, given as inclusive row ranges. Workers cannot see the "
        "task description above, each other, or any rows you do not assign to them. Their reports "
        "will then be combined into one final answer.\n\n"
        f"Write a brief for each of the {workers} workers. {ANSWER_ONLY} "
        "Reply with only a JSON object:\n"
        '{"workers": [{"worker": 1, "brief": "<instructions>", "ranges": [[<first row>, <last row>]]}, ...]}'
    )


def worker_prompt(brief, rows):
    return f"{brief}\n\nYour ledger rows:\n{render_rows(rows)}\n\n{ITEM_FORMAT}"


def merger_prompt(task, reports):
    parts = [TASK_TEXT, "",
             f"{len(reports)} workers each checked part of the ledger. You do not see the ledger. "
             "Their reports:"]
    for w, items in reports:
        if items is None:
            parts.append(f"Worker {w}: (no parseable report)")
        else:
            parts.append(f"Worker {w}: {json.dumps(show_items(items))}")
    parts += ["", "Produce the final report.", ITEM_FORMAT]
    return "\n".join(parts)


def baseline_prompt(task):
    return f"{TASK_TEXT}\n\nThe ledger:\n{render_rows(task['rows'])}\n\n{ITEM_FORMAT}"


# ---------------- generation ----------------

def task_id(size, seed):
    return f"ledgerctx-{size}-s{seed}"


def pair_id(a, b):
    a, b = sorted([a.strip().upper(), b.strip().upper()])
    return f"PAIR:{a}+{b}"


def _codes(rng, n, prefix, length):
    out = set()
    while len(out) < n:
        out.add(prefix + "".join(rng.choice(ID_ALPHABET) for _ in range(length)))
    out = sorted(out)
    rng.shuffle(out)
    return out


def _deviation(rng, expected):
    cents = max(int(expected * rng.uniform(0.01, 0.35)), 37)
    if cents % 100 == 0:
        cents += rng.randint(1, 99)
    return min(cents, expected - 1)


def _place_pairs(rng, n, far, near, taken):
    """Positions (0-based within line items) for far pairs (>= n/2 apart) and near pairs (<= 5)."""
    pairs = []
    for kind, count in (("far", far), ("near", near)):
        while sum(1 for p in pairs if p[2] == kind) < count:
            if kind == "far":
                a = rng.randrange(0, n - n // 2)
                b = rng.randrange(a + n // 2, n)
            else:
                a = rng.randrange(0, n - NEAR_MAX)
                b = a + rng.randint(1, NEAR_MAX)
            if a in taken or b in taken:
                continue
            taken.update((a, b))
            pairs.append((a, b, kind))
    return pairs


def generate(size, seed):
    n, t, k_line, k_ctx, k_far, k_near = SIZES[size]
    rng = random.Random(f"{FAMILY}:{size}:{seed}")
    codes = _codes(rng, t, "RC-", 3)
    rates = {c: rng.randint(1250, 48000) for c in codes}
    rate_rows = [{"row": i + 1, "id": f"RATE:{c}", "rate_code": c, "unit_rate_cents": rates[c]}
                 for i, c in enumerate(codes)]

    line_ids = _codes(rng, n, "RX-", 5)
    claim_ids = _codes(rng, n, "CL-", 6)
    taken = set()
    pairs = _place_pairs(rng, n, k_far, k_near, taken)
    free = [i for i in range(n) if i not in taken]
    rng.shuffle(free)
    under_line = set(free[:k_line])
    under_ctx = set(free[k_line:k_line + k_ctx])
    over = free[k_line + k_ctx:2 * (k_line + k_ctx)]
    over_coded = set(over[: len(over) // 2])
    over_inline = set(over[len(over) // 2:])
    pair_partner = {}
    for a, b, _ in pairs:
        pair_partner[b] = a

    rows = []
    for i in range(n):
        if i in pair_partner:  # second row of a pair: same claim, qty, rate source; paid exactly
            src = rows[pair_partner[i]]
            row = dict(src, row=t + i + 1, line_id=line_ids[i])
            rows.append(row)
            continue
        if i in under_line or i in over_inline:
            coded = False
        elif i in under_ctx or i in over_coded:
            coded = True
        else:
            coded = rng.random() < 0.5
        qty = rng.randint(1, 40)
        code = rng.choice(codes) if coded else None
        rate = rates[code] if coded else rng.randint(1250, 48000)
        owed = qty * rate
        paid = owed
        if i in under_line or i in under_ctx:
            paid = owed - _deviation(rng, owed)
        elif i in over_inline or i in over_coded:
            paid = owed + _deviation(rng, owed)
        rows.append({"row": t + i + 1, "line_id": line_ids[i], "claim_id": claim_ids[i],
                     "qty": qty, "unit_rate_cents": None if coded else rate,
                     "rate_code": code, "paid_cents": paid})

    key = []
    for i in sorted(under_line | under_ctx):
        r = rows[i]
        owed = r["qty"] * (rates[r["rate_code"]] if r["rate_code"] else r["unit_rate_cents"])
        item = {"id": r["line_id"], "value": owed - r["paid_cents"], "row": r["row"]}
        if i in under_ctx:
            item.update(type="context", needs=[r["line_id"], f"RATE:{r['rate_code']}"],
                        context=[f"RATE:{r['rate_code']}"])
        else:
            item.update(type="line", needs=[r["line_id"]])
        key.append(item)
    for a, b, kind in pairs:
        ra, rb = rows[a], rows[b]
        key.append({"id": pair_id(ra["line_id"], rb["line_id"]), "value": None, "type": "pair",
                    "subtype": kind, "needs": [ra["line_id"], rb["line_id"]],
                    "rows": [ra["row"], rb["row"]], "distance": rb["row"] - ra["row"]})
    return {"family": FAMILY, "task_id": task_id(size, seed), "size": size, "seed": seed,
            "n_lines": n, "n_rate_codes": t, "n_rows": n + t,
            "counts": {"line": k_line, "context": k_ctx, "far_pair": k_far, "near_pair": k_near},
            "rate_rows": rate_rows, "line_rows": rows, "rows": rate_rows + rows, "key": key}


# ---------------- rendering and slicing ----------------

def money(cents):
    return "" if cents is None else f"{cents // 100}.{cents % 100:02d}"


def row_id(r):
    return r["id"] if "rate_code" in r and "line_id" not in r else r["line_id"]


def render_rows(rows):
    """Two CSV blocks (rate table, line items); a block is omitted when the slice has none of it."""
    rate = [r for r in rows if "line_id" not in r]
    line = [r for r in rows if "line_id" in r]
    parts = []
    if rate:
        parts.append("Rate table:\n" + ",".join(RATE_COLUMNS) + "\n" + "\n".join(
            f"{r['row']},{r['rate_code']},{money(r['unit_rate_cents'])}" for r in rate))
    if line:
        parts.append("Line items:\n" + ",".join(LINE_COLUMNS) + "\n" + "\n".join(
            ",".join([str(r["row"]), r["line_id"], r["claim_id"], str(r["qty"]),
                      money(r["unit_rate_cents"]), r["rate_code"] or "", money(r["paid_cents"])])
            for r in line))
    return "\n\n".join(parts)


def rows_in_ranges(rows, ranges):
    return [r for r in rows if any(a <= r["row"] <= b for a, b in ranges)]


def show_items(items):
    """Parsed items back into the reply format (what the merger sees, D6)."""
    under = [{"line_id": i["id"], "shortfall": None if i["value"] is None else round(i["value"] / 100, 2)}
             for i in items if i.get("kind") != "pair"]
    dups = [{"line_ids": i["id"][5:].split("+")} for i in items if i.get("kind") == "pair"]
    return {"underpaid": under, "duplicates": dups}


# ---------------- parsing ----------------

_UNDER = re.compile(r"\{[^{}\[\]]*\"line_id\"[^{}\[\]]*\}")
_DUP = re.compile(r"\{\s*\"line_ids\"\s*:\s*\[([^\]]*)\]\s*\}")


def _salvage(text):
    under = []
    for m in _UNDER.finditer(text or ""):
        try:
            under.append(json.loads(m.group(0)))
        except json.JSONDecodeError:
            pass
    dups = []
    for m in _DUP.finditer(text or ""):
        try:
            dups.append({"line_ids": json.loads("[" + m.group(1) + "]")})
        except json.JSONDecodeError:
            pass
    return {"underpaid": under, "duplicates": dups}


def parse_items(text, truncated=False):
    """Parse {"underpaid": [...], "duplicates": [...]} into (items, notes, nonpositive_dropped).

    Underpaid entries follow D13 (shortfall <= 0 counts as not reported). A duplicate counts only
    as a list of exactly two different line ids (D22); anything else is dropped and noted.
    A reply cut off by the output cap keeps its complete entries (D14).
    """
    import swarm  # local import: swarm imports this module
    notes = []
    data = agent.extract_json(text)
    if not (isinstance(data, dict) and ("underpaid" in data or "duplicates" in data)):
        if truncated:
            data = _salvage(text)
            notes.append("reply cut off by output cap; complete entries before the cut used (D14)")
        else:
            return None, ["no JSON object with underpaid/duplicates in reply"], 0
    under = data.get("underpaid") or []
    dups = data.get("duplicates") or []
    if not isinstance(under, list) or not isinstance(dups, list):
        return None, ["underpaid/duplicates is not a list"], 0
    items, nonpositive = [], 0
    under_items, under_notes, nonpositive = swarm.parse_entry_list(under)
    notes += under_notes
    for it in under_items:
        items.append(dict(it, kind="underpaid"))
    seen = set()
    for d in dups:
        ids = d.get("line_ids") if isinstance(d, dict) else None
        if (not isinstance(ids, list) or len(ids) != 2
                or not all(isinstance(x, str) and x.strip() for x in ids)
                or ids[0].strip().upper() == ids[1].strip().upper()):
            notes.append(f"dropped duplicate entry that is not two different line ids: "
                         f"{json.dumps(d)[:80]}")
            continue
        pid = pair_id(*ids)
        if pid in seen:
            notes.append(f"repeated pair in reply: {pid}")
            continue
        seen.add(pid)
        items.append({"id": pid, "value": None, "kind": "pair"})
    return items, notes, nonpositive


def task_block(task):
    return {"family": FAMILY, "task_id": task["task_id"], "size": task["size"],
            "seed": task["seed"], "n_lines": task["n_lines"], "n_rate_codes": task["n_rate_codes"],
            "n_rows": task["n_rows"], "counts": task["counts"], "task_text": TASK_TEXT,
            "structure_text": structure_text(task), "rate_columns": RATE_COLUMNS,
            "line_columns": LINE_COLUMNS, "rows": task["rows"],
            "fixed_sentence": FIXED_SENTENCE}


def items_block(task):
    key = []
    for k in task["key"]:
        item = {"id": k["id"], "value": k["value"], "type": k["type"], "needs": k["needs"]}
        for f in ("context", "subtype", "rows", "distance"):
            if f in k:
                item[f] = k[f]
        key.append(item)
    return {"universe": [row_id(r) for r in task["rows"]], "key": key, "value_unit": "cents"}
