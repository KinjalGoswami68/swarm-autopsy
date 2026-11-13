# Decisions

Every ambiguity in the brief, and the choice made, with the text that forced it.
Quotes are from the project brief (2026-11-13) unless stated otherwise.

## D1. Ledger design: quantity x rate, overpayment distractors

> N line items, each with a contract rate and a paid amount; K of them are planted underpayments.

**Choice (confirmed by owner):** each line has `qty`, `unit_rate` and `paid`; the amount owed is
qty x unit_rate. K lines are planted underpayments, another K lines are overpaid (distractors),
the rest are paid exactly. Deviations are 1%-35% of the owed amount, at least 0.37, and never a
whole number of currency units, so neither size nor roundness gives a planted line away.
Money is held in integer cents; shortfalls in the key are exact. Line ids are random
(`RX-` + 5 characters, no 0/O/1/I) so a worker cannot guess a real id it was never shown.
Payer and service code columns are realistic filler; they do not affect the answer.

**Why:** "rate vs paid" alone is a string comparison and likely too easy to show failures.

## D2. What the planner sees; splits are row ranges only

> planner: sees the task and the line count, writes a brief for each of W workers.

**Choice (confirmed by owner):** the planner sees the task text, the line count and the column
headers, never the rows. It expresses the split only as inclusive row ranges. Content-based
splits (by payer, by service code) are **out of scope for stage 1**. The planner is told that
workers see only their brief and rows, and that reports are combined; it is not told to cover
every row or to avoid overlaps. Coverage and overlap are what the autopsy measures.

## D3. Brief count and planner failure

**Choice (confirmed by owner):** briefs past W are ignored and logged in `parse_notes`. Fewer
than W briefs are allowed (a split choice). Ranges outside 1..N are clamped; malformed ranges
are dropped and logged. If the planner reply yields no usable brief, no worker and no merger is
called and every key item lands in "never assigned". There is no fallback split: a fallback
would hide exactly the failures this tool exists to show.

## D4. Temperature 0, reasoning at provider default

**Choice (confirmed by owner):** temperature 0 and no `reasoning_effort` parameter (the
provider default). Chosen for reproducibility: re-running a run should give the same calls.
Real swarms usually run warmer, so **failure rates measured here may be lower than in
practice**. Seeds vary the task, not the sampling.

## D5. What a worker receives

> workers: each gets only its brief and the ledger slice the brief names

**Choice:** a worker gets its brief, its rows (header included, same format as the baseline),
and one output-format line added by the harness (`ITEM_FORMAT` in `swarm.py`). It does not get
the task text; if the brief omits the rule for "underpaid", that is a split-stage failure.
**Why the format line:** without it the reply cannot be parsed, and format is not under test.
The baseline and the merger get the same format line.

## D6. What the merger receives

> merger: gets the task and the workers' outputs

**Choice:** the task text plus each worker's parsed items, re-serialised as JSON and labelled by
worker number. It does not get the ledger, the briefs or the workers' prose. An unparseable
worker reply is shown as "(no parseable report)". Re-serialising the parsed items means the
autopsy's "a worker reported it" is exactly what the merger saw.

## D7. Matching a reported item to the key

**Choice (confirmed by owner):** an item is found when its line id matches a key line id
(case-insensitive, whitespace trimmed). The reported shortfall does not affect buckets.
Shortfall accuracy is a separate number: a found item is accurate when its reported shortfall
is within 1 cent of the key.

## D8. Transport, cache and stop rules (copied from swarm-failure-lab)

Copied from `swarm-failure-lab/agent.py`: retries on 429, 5xx and network errors with backoff
1-32 s; a `retry-after` over 120 s or exhausted retries stops the run (`RateLimitStop`). Every
successful response is cached (atomic write) under a key of model, temperature,
reasoning_effort, messages, call id and endpoint. Failed calls are never cached. A non-retryable
4xx is recorded in the run as a failed call. **New:** a 413, or any "request too large" error,
raises `RequestTooLarge` and stops the run, since retrying cannot help.

## D9. Size L does not fit the free tier in one call (open: awaiting owner decision)

> Rs 0, Groq free tier, default model qwen/qwen3.8-27b

Live check on 2026-11-13, size L seed 1, baseline prompt: HTTP 413 from Groq,
"input tokens per minute (ITPM): Limit 7000, Requested 24702". The rendered ledger costs about
41 input tokens per line, so the single-agent baseline also exceeds 7,000 at size M
(estimate ~8,300). Size S (~2,600) fits. Per the owner's instruction, the grid was not run.
