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

## D9. Free-tier input limit: shorter rows; size L is swarm only

> Rs 0, Groq free tier, default model qwen/qwen3.8-27b

**Finding (2026-11-13):** size L seed 1, baseline prompt, original row format (7 columns,
`|`-separated): HTTP 413, "input tokens per minute (ITPM): Limit 7000, Requested 24702"
(about 41 input tokens per line). A single request cannot exceed 7,000 input tokens.

**Choice (confirmed by owner):**
1. **Shorter rows.** Payer and service code are dropped (they were filler, D1) and rows are
   CSV: `row,line_id,qty,unit_rate,paid`. The planner sees these five column headers (D2).
   **Measured** with one size-S call (seed 1 baseline, 60 lines): 1,748 prompt tokens for
   2,324 prompt characters, i.e. 1.33 characters per token (digits tokenise almost one per
   token). That is 29.1 tokens per line including the fixed prompt text, or about 22.4 tokens per
   line for the table alone. Projected one-call baselines: S about 1,750 (measured), M about
   4,900, L about 14,700 input tokens.
2. **S and M run swarm and baseline. L stays 600 lines and runs the swarm only.** The L
   baseline call is still sent, so the provider measures its size; it is recorded as
   `status: rejected_too_large`, `final: null`, with `requested_tokens` and `limit_tokens`.
   The table shows "did not fit in one call" with those numbers, **never a score of zero**.

## D10. Pacing to the per-minute limits

**Choice:** a client-side sliding window (`agent.Pacer`) waits before each live call until the
input tokens sent in the last 60 s plus this call's estimate fit under `--itpm` (default 7000).
The estimate is characters / 1.2 (a little more pessimistic than the measured 1.33) and is
replaced by the real `prompt_tokens` once the call returns. Cached calls are not paced. A 429
with a short `retry-after` is still retried (D8), so the pacer only has to be close.

## D11. A call rejected as too large is a recorded failure, not a crash

**Choice (confirmed by owner):** any planner, worker, merger or baseline call the provider
rejects as too large is recorded as `status: rejected_too_large` with the requested size and
limit. A rejected worker is treated as having reported nothing; its parse note reads "worker
call rejected: request too large", the run carries on, and the table footnotes it. If the
planner gives one worker too many rows, that is a split failure. Only a real rate limit (429 with
a wait over 120 s, or exhausted retries) stops the run, with exit code 2, to be resumed later.

## D12. Output cap and free-tier output limit (open: awaiting owner decision)

**Finding (2026-11-13):** the size-S measurement call stopped at exactly 2,048 completion tokens,
inside its line-by-line working (39 of 60 lines), so no JSON was produced. `max_tokens` had not
been sent, so the provider default applied. A retry with `max_tokens=32768` was refused (400:
the maximum is 16,384). A retry with `max_tokens=16384` was refused before running: "Request too
large ... on output tokens per minute (OTPM): Limit 1000, Requested 2048".

The model writes about 40 output tokens per line when it shows its working, so any prompt over
about 45 lines would be cut off by the provider, not missed by the model. Changes made:
`max_tokens` is a CLI flag and part of the cache key; every call records `finish_reason`; a
reply cut off by the cap has `status: truncated`, separate from `unparseable`.
