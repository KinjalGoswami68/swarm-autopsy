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

## D12. Output cap and free-tier output limit: answer-only replies

**Finding (2026-11-13):** the size-S measurement call stopped at exactly 2,048 completion tokens,
inside its line-by-line working (39 of 60 lines), so no JSON was produced. `max_tokens` had not
been sent, so the provider default applied. A retry with `max_tokens=32768` was refused (400:
the maximum is 16,384). A retry with `max_tokens=16384` was refused before running: "Request too
large ... on output tokens per minute (OTPM): Limit 1000, Requested 2048".

The model writes about 40 output tokens per line when it shows its working, so any prompt over
about 45 lines would be cut off by the provider, not missed by the model. Changes made:
`max_tokens` is a CLI flag and part of the cache key; every call records `finish_reason`; a
reply cut off by the cap has `status: truncated`, separate from `unparseable`.

**Choice (confirmed by owner):** answer-only replies for every role, baseline included. The
shared format line starts "Do not show your working or any explanation." and the planner gets
the same sentence. `max_tokens` is not sent (sending more than the free-tier output limit is
refused), so the provider's default cap of 2,048 output tokens applies. The pacer also keeps
completion tokens under `--otpm` (default 1000) per minute (D10).

**All results in this project are under this constraint.** The model computes qty x unit_rate
without visible working, so **arithmetic misses are expected to be higher than with visible
working**, for the swarm and the baseline alike.

**Re-measurement (2026-11-13), size S seed 1 baseline, answer-only:** 1,754 input tokens
(29.2 per line including the fixed prompt text), 1,353 output tokens, finish_reason `stop`. All 12
planted items were listed (2 of 12 shortfalls correct to the cent), but the reply listed 57
of 60 lines, most with `"shortfall": 0.00`. See D13.

## D13. Replies that list non-underpaid lines: positive-only prompt and scoring rule

The answer-only S baseline (D12) listed 57 of 60 lines, most with shortfall 0.00, despite the
task text ("must not be reported") and the format line ("Use [] if there are none").

**Choice (confirmed by owner):**
1. **Prompt.** The format line given to every role and to the baseline adds "List only lines
   whose shortfall is greater than 0."
2. **Scoring rule.** An entry whose own reported shortfall is 0 or negative is the reply saying
   "not underpaid", so it **counts as not reported**. This applies to workers, merger and baseline
   alike. The count is stored per call as `nonpositive_dropped` with a parse note, and the raw
   reply stays in the run file. An entry whose shortfall cannot be read as a number still counts
   as reported, because the reply named the line. Dropped worker entries are not shown to the
   merger, since D6 shows only parsed items.

**Re-check (2026-11-13), size S seed 1 baseline:** 1,765 input / 1,342 output tokens,
finish_reason `stop`. The sentence did not change the behaviour: the reply still listed 57
lines; 50 had shortfall <= 0 and were dropped by the rule, leaving 7 reported (6 of 12 planted
lines found, 1 shortfall correct to the cent). About 23.5 output tokens per listed line, so M
baselines and L workers that list every line will still hit the 2,048 output cap (D14).

## D14. Replies cut off by the output cap: keep the complete entries before the cut

Decided under the owner's standing rule (provider limits: treat swarm and baseline the same,
record, continue).

**Choice:** when a reply ends with `finish_reason: "length"` and its JSON array never closed,
the complete `{...}` entries before the cut are parsed (then D13 applies). Status stays
`truncated`, the parse note says how many entries were used, and the table footnotes every
truncated call. This applies identically to workers, merger and baseline. Replies that were
not cut off are never salvaged this way.

**What this means for the numbers:** a key line that a truncated reply never reached is
counted as missed: "assigned, missed" for a worker, a miss for the baseline. Some of those
misses are caused by the output cap, not by the model's judgement. The footnotes say which
runs this affects. Splitting these out ("unreached: output cap") would be a new bucket, so it
needs the owner's decision and has not been done.


## D15. First grid discarded: output-limit rejections misread, cache key mismatch

Decided under the owner's standing rule (provider limits and pacing).

**What happened (2026-11-13, first grid, 9 runs):** 15 calls, including tiny planner prompts,
were refused with HTTP 429 "Request too large ... on output tokens per minute (OTPM): Limit
1000, Requested 1342" (also 1353 and 1425). With no `max_tokens` sent, Groq sets a request's
expected output from recent replies (1342, 1353 and 1425 were earlier baseline reply sizes) and
refuses the request when that estimate is over the 1,000-per-minute output limit. The harness
treated these as "did not fit in one call", which is wrong: the prompts fit. Also, the CLI
passed temperature `0.0` where the measurement calls used `0`, so the cache keys differed and
no measured call was reused. Those 9 run files were deleted; they measured the harness, not
the swarm.

**Choice:**
1. Every call sends `max_tokens` equal to the per-minute output limit (`--otpm`, default 1000),
   so the provider's expected output never exceeds the limit. Same for every role and the
   baseline. **Effect: replies are cut off at 1,000 output tokens, not 2,048** (about 42 listed
   lines at about 23.5 tokens each). Cut-off replies follow D14.
2. The output pacer counts each call as max(completion tokens, max_tokens) and waits until the
   window has room for a full max_tokens reply: about one call per minute.
3. A rejection records `limit_kind` (`input` or `output`). Only an `input` rejection of the
   baseline is shown as "did not fit in one call"; anything else is "not scored" with a per-run
   footnote. Neither is ever a score of zero.
4. Temperature is cast to float in the cache key, so 0 and 0.0 share a key.
5. CLI output is UTF-8, so the footnote markers print correctly on Windows.

## D16. Grid results (2026-11-13) are dominated by the output cap at M and L

Observation, not a choice. The 9-run grid finished with no stops. With the 1,000-token output cap
(D15), every L worker and most M workers were cut off (`truncated`), as were 5 of the 6 S/M
baselines. An ad-hoc count (not part of the autopsy): of the swarm's "assigned, missed" items,
**99 of 129 at size L sat in a cut-off worker's slice after the last line that worker reached**
(L seeds 1/2/3: 33/40, 31/44, 35/45). At M it was 4 of 33; at S, 0 of 6. Those L losses are
caused by the provider's output cap, not by the workers' judgement. Tracking this as its own
bucket ("assigned, unreached: output cap") would change the scoring buckets, so it awaits the
owner's decision. M seed 2 lost all 24 items because the planner's own reply (four long briefs)
was cut off before its JSON closed, so no split existed.

## D17. New bucket: "assigned, unreached (reply cut off)"

**Choice (confirmed by owner):** a fifth bucket, checked after "dropped at merge" and before
"assigned, missed". A key item is **assigned, unreached** when at least one worker had it in its
slice and **every** such worker's reply was cut off (`status: truncated`) before reaching it.
A worker "reached" an item when that item's id, or any id later in the worker's slice order,
appears in the reply text as a whole token (entries dropped by D13 count as reached). If any
holder was not cut off, or reached the item, it stays "assigned, missed". The rule needs
only `slice` order and `call.raw_text`, both already in every run file, so the 9 qwen run files
were re-scored without model calls and kept as the qwen results.

The baseline has no buckets, but its autopsy now reports `missed_unreached` (misses after its
own reply was cut off). This is information only; it does not change its score.

## D18. Model change to openai/gpt-oss-120b: probes (open: awaiting owner decision)

**Why change model (owner, 2026-11-13):** the qwen/qwen3.8-27b free tier cannot carry this
experiment: 7,000 input tokens per request, 1,000 output tokens per minute and a 1,000-token
reply cap (D9, D12, D15) cut off most M and L replies (D16, D17).

**Probes (2026-11-13), seed 1 baselines, answer-only prompts, temperature 0, reasoning at the
provider default, no pacing.** Limits stated by Groq: 8,000 tokens per minute counting input
and requested output together (headers `x-ratelimit-limit-tokens: 8000`, 1,000 requests),
and 200,000 tokens per day (owner). Reasoning tokens count as output.

| size | max_tokens | input | output incl. reasoning | finish | result |
|---|---|---|---|---|---|
| S | not sent (default cap 3,072) | 1,351 | 3,072 | length | no answer: reasoning used the whole cap |
| M | not sent (default cap 3,072) | 3,997 | 3,072 | length | no answer: reasoning used the whole cap |
| L | not sent | – | – | – | HTTP 413: TPM limit 8000, requested 14,662 |
| S | 6,500 | 1,351 | 3,398 | stop | listed only underpaid lines: 12/12 found, 0 false positives |
| M | 3,900 (= 8,000 − input − margin) | 3,997 | 3,900 | length | no answer: reasoning used the whole cap |

**Consequence:** with default reasoning, the M baseline cannot finish within the 8,000-token
per-minute limit, whatever max_tokens is set to. Grid not started.

## D19. gpt-oss-120b with reasoning_effort=low: probes; Gemini probe blocked

**Probes (2026-11-13), seed 1 baselines, answer-only prompts, temperature 0,
`reasoning_effort: low`** (would replace D4's provider-default reasoning; owner approved the probe only):

| size | max_tokens | input | output incl. reasoning | finish | result |
|---|---|---|---|---|---|
| S | 6,500 | 1,351 | 1,687 | stop | only underpaid lines listed: 12/12 found, 0 false positives, 11/12 shortfalls exact |
| M | 3,900 | 3,997 | 48 | stop | replied `[]`: 0/24 found. Reasoning text: "Hard to compute all. Might assume none? ... I'll output []" |

The M call fit within the limits; the empty answer is the model giving up, not a cut-off, so
it would score as a genuine miss.

**Gemini probe blocked:** the owner's message said a Google AI Studio key was in `.env` as
`LLM_API_KEY`. On 2026-11-13 `.env` held only `GROQ_API_KEY` (unchanged since it was copied
in), and `LLM_API_KEY` in `.env.example` is empty. The OpenAI-compatible `/models` call
without a key returned 404. No Gemini call has been made.

## D20. Gemini 3.8 Flash probes; model choice (open: awaiting owner confirmation)

Endpoint `https://generativelanguage.googleapis.com/v1beta/openai` (`--endpoint`), key
`LLM_API_KEY`. The key's model list includes `models/gemini-3.8-flash`, the model Acyclic's
README names for its pilots; it is used as `gemini-3.8-flash`.

**Probes (2026-11-13), seed 1 baselines, answer-only prompts, temperature 0, no max_tokens,
reasoning at the provider default.** Gemini reports hidden "thinking" only inside
`total_tokens`, so output including reasoning = total − prompt (`agent.py` now stores the full
`usage` block of every call).

| size | input | visible output | output incl. thinking | finish | listed only underpaid | recall | false positives | shortfalls exact | latency | retries |
|---|---|---|---|---|---|---|---|---|---|---|
| S | 1,779 | 325 | 4,165 | stop | yes | 12/12 | 0 | 12/12 | 143 s | 0 |
| M | 5,688 | 643 | 10,033 | stop | yes | 24/24 | 0 | 24/24 | 181 s | 4 |
| L | 17,011 | 1,297 | 28,930 | stop | yes | 48/48 | 0 | 48/48 | 221 s | 1 |

**Limits:** no rate-limit headers were returned. The 5 retries (429 or 5xx) were absorbed by
the backoff, and their messages were not kept. Google's public rate-limit page does not list
free-tier numbers for this model; it says limits apply per project and requests-per-day reset at
midnight Pacific time, and points to the signed-in page aistudio.google.com/rate-limit.

**Consequence if chosen:** the single-agent baseline is perfect on seed 1 at every size, so on
this task any swarm loss is a loss the model alone does not make. Baseline quality is
measured on one seed per size only.

## D21. Default model: gemini-3.8-flash

**Choice (confirmed by owner, 2026-11-13):** the default model is `gemini-3.8-flash` on Google
AI Studio's OpenAI-compatible endpoint, free tier (key `LLM_API_KEY`). **Reason:** it is the
only candidate whose single-agent baseline fits one call at every size (S, M, L), with no
output cap cutting replies off (D20). The qwen/qwen3.8-27b free tier on Groq cut off most M and L
replies (D16, D17), and gpt-oss-120b's 8,000 tokens-per-minute limit left no room for an M or L
baseline (D18, D19). It is also the model Acyclic's README names for its pilots.

Consequences:
- CLI defaults: `--model gemini-3.8-flash`, `--endpoint` = the Gemini URL. The 9 qwen run files
  stay in `runs/` as the qwen results; the table is filtered by `--model`.
- Pacing is **off by default** (`--itpm 0 --otpm 0`), so no `max_tokens` is sent and the provider
  default applies. The qwen settings (7000/1000, D10, D15) are passed explicitly for Groq runs.
  Rate limits are absorbed by the retry rules (D8). Free-tier numbers for this model are not
  published (D20); the owner will supply them.
- HTTP timeout raised from 300 to 600 s (L baseline took 221 s).
- Thinking stays at the provider default and is hidden; answer-only prompts (D12) still apply
  to every role, so swarm and baseline are treated the same.


## D22. Task family 2, "ledger-ctx": a ledger built so that splitting can hurt

**Design (approved by owner, 2026-11-13).** Code: `ledger2.py`. Task ids `ledgerctx-<size>-s<seed>`.

- **Rate table:** rows 1..T (`row,rate_code,unit_rate`); T = 10 / 20 / 40 for S / M / L.
- **Line items:** rows T+1..T+N (`row,line_id,claim_id,qty,unit_rate,rate_code,paid`); N = 60 / 200 / 600.
  Each row fills exactly one of `unit_rate` or `rate_code`; about half are coded (owner, Q1).
- **Planted key items**, each with `type` and `needs` (the rows a correct judgement requires):
  `line` = underpaid row with an inline rate (needs its row); `context` = underpaid row with only
  a rate code (needs its row and that code's table row, the latter listed in `context`);
  `pair` = one claim_id billed on two rows, both paid normally (owner, Q6), id
  `PAIR:<idA>+<idB>` (sorted), subtype `far` (at least N/2 rows apart) or `near` (1 to 5 rows
  apart, a control). Counts (owner, Q5): S = 4 line, 4 context, 3 far pairs, 1 near pair; M and L
  x2 and x4. Distractors: as many overpaid rows as underpaid ones, half inline and half coded.
  All other claim_ids are unique.
- **Planner sees** the task text, the section row ranges and both header lines, never the rows or
  the rate table's contents (owner, Q2). It expresses the split as row ranges only (D2); a worker
  gets the table only if its ranges include rows 1..T.
- **Pair scoring (owner, Q4):** a pair counts only when reported in `duplicates` with exactly
  both ids. A reported pair sharing one id with a key pair is a false positive of kind
  `half_pair`; any other wrong pair is `wrong_pair`. Duplicate entries that are not two different
  line ids are dropped and noted. D13 (shortfall <= 0 means not reported) applies to `underpaid`.
- **Answer-only prompts** are kept (owner, Q8). Thinking stays hidden at the provider default.
- **New autopsy buckets**, checked after "dropped at merge" and before "assigned, unreached" and
  "assigned, missed": **never assigned** = no slice held any of the item's own rows (its needs
  minus context rows); **context not passed** = some worker held the item's own row but no worker
  held it together with the rate-table row it needs ("the worker's slice lacked the table row",
  owner, Q2); **evidence split across workers** = its rows were assigned but no single slice held
  all of them. Unreached and missed then require a worker holding every needed row. Items with
  no `needs` count as needing only themselves, so schema-1 runs score exactly as before.
- **Fixed sentence (owner, Q7)**, shown on every table, autopsy and site page with these runs:
  "This family is built so that splitting can hurt; its numbers show the autopsy detects split and context failures, not how often swarms lose in general."
- **Run files** are `schema_version: 2`: key items may carry `type`, `needs`, `context`,
  `subtype`; reported items carry `kind` (`underpaid` or `pair`). Rate-table rows have ids
  `RATE:<code>` and are part of `universe` and of slices.

**Frozen prompt wording (owner, Q3).** Fixed before any family-2 call and never to be adjusted
after seeing results. Only the numbers (rows, T, W) are filled in. Planner prompt as rendered for
size S, W = 4:

```
You are auditing a remittance ledger with two sections. The rate table lists rate codes and their unit rates. Each line item is one billed service; it gives either its own unit_rate or a rate_code whose unit rate is in the rate table. The amount owed for a line is qty x unit rate. A line is UNDERPAID when paid is less than the amount owed; its shortfall is (amount owed) - paid, in currency units with two decimals. Lines paid exactly, or overpaid, are not underpayments and must not be reported as underpaid. A claim is DUPLICATED when the same claim_id appears on more than one line item (billed more than once). Find every underpaid line and every duplicated claim.

The ledger has 70 rows. Rows 1 to 10 are the rate table, with columns:
row,rate_code,unit_rate
Rows 11 to 70 are line items, with columns:
row,line_id,claim_id,qty,unit_rate,rate_code,paid
A line item gives either its own unit_rate or a rate_code defined in the rate table. A claim_id may appear on more than one line item.
You will not see the rows themselves.

You coordinate 4 workers. Each worker receives only the brief you write for it and the ledger rows you assign to it, given as inclusive row ranges. Workers cannot see the task description above, each other, or any rows you do not assign to them. Their reports will then be combined into one final answer.

Write a brief for each of the 4 workers. Do not show your working or any explanation. Reply with only a JSON object:
{"workers": [{"worker": 1, "brief": "<instructions>", "ranges": [[<first row>, <last row>]]}, ...]}
```

Format line given to every worker, the merger and the baseline:

```
Do not show your working or any explanation. Reply with only a JSON object: {"underpaid": [{"line_id": "<line_id>", "shortfall": <amount with two decimals>}], "duplicates": [{"line_ids": ["<line_id>", "<line_id>"]}]}. List only lines whose shortfall is greater than 0. Use empty lists if there are none.
```

Workers get `<brief>` + "Your ledger rows:" + their rows as up to two CSV blocks ("Rate
table:" and/or "Line items:", each with its header) + the format line. The merger gets the
task text, each worker's parsed items re-serialised in the reply format (D6), "Produce the final
report." and the format line. The baseline gets the task text, the whole ledger and the format line.

## D23. Gemini free tier: 20 requests per day, retries included

Decided under the owner's standing rule (provider limits and pacing).

**Finding (2026-11-13):** the family-2 probe stopped on HTTP 429 "Generate content requests per
day limit exceeded on Free Tier", quotaId `GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
**quotaValue 20**, reset at midnight Pacific time. By then the day had 9 successful
gemini-3.8-flash calls and 11 retried attempts (429 or 5xx, absorbed by the D8 backoff), exactly
20: **every HTTP attempt counts against the daily quota, including rejected ones.** The first pass
(old ledger, seed 1) finished size S only; it was stopped by hand before M. The family-2
probe made no successful call.

**Choice:**
1. A 429 whose body names a per-day quota stops the run immediately (no retries), with the
   quota id, limit and reset time in the message.
2. A per-minute 429 waits for the provider's stated `retryDelay` (+1 s) instead of 1–32 s backoff.
3. `--rpd` (default 20) counts every HTTP attempt per model per Pacific-time day in
   `cache/requests.json` and stops cleanly *before* an attempt that would exceed it. Pacific
   time is taken as UTC-8 all year; the provider's own 429 is the backstop during US summer time.
   Today's count was seeded with 21 (20 above plus one request made to read the full error).

**Consequence:** about 20 calls per day, fewer when retries occur. One seed of one family at
S, M and L with W=4 is about 21 calls (18 swarm + 3 baseline); the full family-1 grid (S, M,
L W=4, L W=12, 3 seeds) is about 105 calls, so about 6 days. Owner to decide whether that is
acceptable.

## D24. Plan change: family 2 is the experiment, the axis is the number of workers

**Owner decision (2026-11-13). Reason:** at 20 Gemini requests per day (D23) the full old-ledger
grid would take about 6 days, and the old ledger is the wrong test anyway: when every line can
be judged alone, splitting has nothing to lose (qwen results D16/D17; Gemini S seed 1: 12/12
kept, 0 lost in any bucket).

1. **Old-ledger grid dropped.** The Gemini S seed-1 run and the 9 qwen run files stay as the
   evidence that splitting loses nothing when lines are independent. The queued Gemini M and L
   old-ledger runs were cancelled before they started.
2. **Groq, openai/gpt-oss-120b, default reasoning:** family 2 at size S, W = 2, 4 and 8, seeds
   1 to 3, swarm plus one baseline per seed (the baseline call does not depend on W, so it is
   made once per seed and reused from the cache). After a one-call probe of the S baseline.
3. **Gemini gemini-3.8-flash, 20 requests per day:** family 2 at size M, one run per day in the
   background (day 1: baseline + W=4; later days: other W, baseline from cache).
4. **Table for the Groq runs:** one row per W.

**Mechanics for gpt-oss (provider limits, under the owner's standing rule):** Groq counts input
plus requested `max_tokens` against one 8,000 tokens-per-minute limit (D18). `--max-tokens-total
8000` sets each call's `max_tokens` to 8,000 − (input estimated at 1.5 characters per token, above
the 1.74 measured, + 100) − 100, so the request never exceeds the limit; `--tpm 8000` paces calls on
a combined 60-second window. A rejection on that limit is recorded with `limit_kind: combined`.
Groq's 200,000 tokens-per-day limit message says "per day", so it stops the run at once (D23).
Groq runs pass `--rpd 1000` (Groq's daily request limit for this model, from its headers).

## D25. gpt-oss-120b, default reasoning, does not answer the family-2 S baseline (open)

**Probe (2026-11-13),** family 2 (`ledgerctx-S-s1`) baseline, openai/gpt-oss-120b on Groq,
temperature 0, default reasoning, `--max-tokens-total 8000`: prompt 3,663 characters = 1,969
input tokens (1.86 characters per token), `max_tokens` sent 5,358. Reply: 5,358 completion
tokens, `finish_reason: length`, no answer (0 of 12 key items), latency 557 s. The owner's
condition for the W = 2/4/8 runs ("if it fits and answers") is not met; nothing else was run.
At most about 5,900 output tokens could be requested within the 8,000 combined limit even with
an exact input estimate. About 7,300 of the day's 200,000 tokens were used.

## D26. gpt-oss-120b on family 2 uses reasoning_effort=low

**Owner decision (2026-11-13), replacing D4's provider-default reasoning for the Groq family-2
runs only.** Reason: with default reasoning the model did not answer the family-2 S baseline
within the 8,000-token combined limit (D25). Low reasoning answered the old-ledger S baseline
fully (12/12, 0 false positives, D19). Every role and the baseline use the same setting, so
swarm and baseline are still treated the same. Known risk: at old-ledger M, low reasoning gave
up and answered `[]` (D19). Rule set by the owner: if the probe gives up or returns an empty
list, stop and report.

## D27. "Assigned, missed" split by fact; model-read brief annotations

**Owner decision (2026-11-13).** No change to prompts, sizes or models.

1. **Bucket split, deterministic, from the run file only.** "Assigned, missed" is replaced by
   two buckets. Both apply to an item whose every needed row was held by at least one worker
   that was not cut off before them (the "reaching holders"):
   - **assigned, holder returned nothing** (`holder_returned_nothing`): every reaching holder's
     parsed `reported` list is empty. An empty list after D13 (all entries had shortfall <= 0),
     or a reply with no usable JSON, also counts as empty: the worker reported nothing usable.
   - **assigned, holder answered, missed it** (`holder_answered_missed`): at least one reaching
     holder reported other items but not this one.
   The "baseline also missed" cross-check covers both. Old run files are re-scored with no
   model calls; the qwen and Gemini old-ledger tables gain one column.
2. **Brief annotations** (`judge.py`, `cli.py annotate`), **separate from the buckets and never
   changing a score.** One cached judge call per brief at temperature 0, two yes/no questions,
   each with the brief's exact sentence quoted as evidence: (a) does the brief rely on something
   the worker was not given (another worker's output, or rows outside its slice)? (b) does it
   limit the worker to some kinds of finding? The judge is told only facts that are certain from
   the run file (the worker's rows, whether they include the rate table, that workers cannot see
   each other, the kinds of finding). Each quote is checked against the brief text
   (`quote_verified`, ignoring whitespace, case, and dash or quote style). Stored in the run file
   under `annotations` with the label "model-read annotations"; shown beside the bucket table as
   "why" and in each autopsy as "why (model-read annotation)".
   **Judge:** openai/gpt-oss-120b on Groq, reasoning_effort low, `--max-tokens-total 3000`
   (briefs are short; a smaller request lets about three calls fit per minute). This is the
   run's own model, chosen because Gemini's 20 daily requests are committed to the size-M
   schedule (D24); it is not an independent reader, so its annotations were checked by hand.

**Hand check of the annotations (2026-11-13), all 42 briefs of the nine family-2 gpt-oss runs,
read against the brief text and the worker's rows:**
- **(a) relies on something not given: 42 of 42 correct.** Every "yes" quote is the right sentence
  (e.g. "Assume the rate table from rows 1-10 is globally available for lookup.", "Same as
  Worker 2.", "Using the rate-code lookup built by Worker 1 ...").
- **(b) limits the worker to some kinds: 10 wrong, 1 debatable, 31 correct.** Two error patterns:
  (1) 7 briefs that ask for both kinds but say to report duplicates "within the rows you
  processed" were marked "yes": a scope limit read as a kinds limit (all six W=2 briefs, and
  seed 2 W=8 worker 8); (2) 3 table-only briefs ending "No further output is required" or "No
  calculations are needed here" were marked "no" although they ask for no finding at all (seed 2
  and 3 W=4 worker 1, seed 2 W=8 worker 1). Debatable: seed 1 W=4 worker 2 asks for "claim_id
  counts", not duplicates as such; the judge said yes there but no for workers 3 and 4, which ask
  the same. In every wrong case the judge's own `kinds` list was right and contradicted its
  yes/no answer.
- **Quotes:** 3 "yes" quotes were shortened with "..." and are correctly flagged
  `quote_verified: false`; all others are verbatim.
- Hand-corrected counts of (b) "yes": W=2 0 of 6 (judge 6), W=4 9 of 12 (judge 8), W=8 23 of 24
  (judge 23; two errors cancel). The (a) counts need no correction: 3, 9, 19.

**Open (owner to decide):** derive (b) deterministically from the judge's `kinds` list (yes when
it lists fewer kinds than the task has) instead of its yes/no answer. On these 42 briefs that
would agree with the hand check in every case except the debatable one.

## D28. Annotation (b) is derived from the judge's kinds list

**Owner decision (2026-11-13).** Answer (b), "does the brief limit the worker to some kinds of
finding", is now "yes" exactly when the judge's own `kinds` list names fewer kinds than the task
has; the judge's yes/no is kept as `judge_answer`. When the list is missing or unusable, the
yes/no is used. The 42 stored annotations were re-derived from their saved replies (no model
calls). Result: (b) "yes" in 0 of 6 briefs at W=2, 9 of 12 at W=4, 23 of 24 at W=8, matching the
hand check (D27) in every case; the debatable seed-1 W=4 worker-2 brief ("claim_id counts")
now reads "no". Annotations still never change a score.


## D29. Stage 2: replays

**Owner decision (2026-11-13).** A replay re-runs part of a stored run with one thing changed and
reports how many key items come back. Code: `replay.py`, `cli.py replay` / `replay-table`.
Each replay is a labelled counterfactual stored as `runs/replays/<run_id>__<label>.json` (a full run
record with a `replay` block: `of`, `label`, `name`, `change`). **The original run files and the
frozen planner wording (D22) are never changed.** Workers and merger are re-run with the run's own
model and settings (endpoint, temperature, reasoning effort, max_tokens_total from its `config`).
The baseline is copied from the original, not re-run. Replay calls use their own cache ids
(`[task, "replay", label, role, ...]`).

- **R1 table to everyone:** the planner's slices unchanged, plus the rate-table rows added to every
  worker's slice. Briefs unchanged.
- **R2 neutral briefs:** the planner's slices unchanged; every brief replaced by
  "Report every underpaid line and every duplicate claim you can establish from the rows you were given; you cannot see anything else and cannot contact other workers."
- **R3 both:** R1 and R2 together.
- **R4 planner told the truth:** the frozen planner prompt with one sentence inserted right after
  "Their reports will then be combined into one final answer.": "Workers cannot communicate with each other, and each worker sees only its own rows." New planner call, then workers and merger.

**Reuse rule (decided under the standing rule, it does not change what a number means):** a worker
or merger whose prompt is byte-identical to the original's reuses the original output
(`reused_from_original: true`) instead of a new call, so a difference between a replay and its
original comes only from the change, not from re-sampling. (Example: under R1 a worker whose slice
already held the rate table gets an identical prompt.) A worker with no rows under the planner
(seed 2 W=8 worker 8) gets the table only under R1.

**No merge replay:** in all nine original runs "found, dropped at merge" is 0, so a merge
counterfactual has nothing to recover. **Far pairs** come back only when both rows land with one
worker; R1-R3 keep the planner's slices (R1/R3 only add the rate table), so they cannot recover a
far pair; only R4 can. Far and near pairs are reported separately.

**Report per replay:** recall, the bucket breakdown, items recovered (kept in the replay, not in
the original) and items newly lost (kept in the original, not in the replay).

## D30. Stage 3 build decisions (site mechanics)

Decided under the owner's standing rule; none changes what a number means.

- **Every number is computed in the browser** by `site/js/autopsy.js`, a line-for-line port of
  `autopsy.py`. `tests/test_site_parity.py` runs it under Node on every committed run and replay
  file plus edge-case runs and requires output identical to Python's, including list order and
  message text. Percentages round halves to even, as Python's `:.0f` does.
- **Schema check in the browser:** `site/js/validate.js` implements exactly the JSON Schema keywords
  `schema/run.schema.json` uses and refuses a schema with any other keyword, so it cannot silently
  skip a rule. Chosen over bundling Ajv: no third-party code, and the site makes no external
  requests (owner). `tests/test_site_validate.py` checks it accepts and rejects the same files as
  Python's `jsonschema` (all committed files, plus 11 broken variants).
- **"Try your own run" reads files locally** (File API); nothing is uploaded, no key.
- **Model output is inserted as text only**, never as HTML (briefs and replies are model output).
- **Loading:** `build_site.py` writes `_site/manifest.json` with file paths only (no numbers) and
  copies the run files; the browser loads at most 4 files at a time.
- **Local preview:** `tools/serve.mjs` (Node). Python's `http.server` reset connections mid-file
  on this Windows machine (curl exit 56 on about half the fetches of the 168 KB files); the Node
  server passed 87 of 87 complete fetches. GitHub Pages is not affected.
- **360 px check:** `tools/check_mobile.mjs` emulates a 360 px phone through Chrome's DevTools
  protocol (headless Chrome's window cannot be narrower than about 500 px) and fails if any page
  is wider than the viewport.
- **Deploy:** `.github/workflows/pages.yml` on push to `main`: install, run the full test suite
  (the parity tests gate the deploy), `build_site.py`, publish `_site/` with GitHub's Pages actions.

## D31. Site styling from the measured reference values

**Owner decision (2026-11-13):** style from colour and layout values measured from the reference
image (the image itself is not in the repo), with DESIGN.md and SITE_RULES.md.

- **Colours:** page #0a0a0a, card #111111, plum panel #3a1533, accent pink-violet #e39bd2, primary
  text #f2f2f2, secondary text #9a9a9a, track/divider #3a3a3a, hairlines #2a2a2a. Metallic plum is
  built from #3a1533 with a lighter band #4d1d44 and a darker edge #24091f.
- **Contrast (WCAG AA, checked before use):** primary text 17.7:1 on the page, 16.9 on cards,
  14.1 on plum; secondary 7.0 / 6.7 / 5.6, and 4.7 on the plum highlight; pink 9.3 / 8.9 / 7.4.
  Bars on the track: pink 5.4, grey 4.0, near-white 10.2. **Plum is a surface only, never text
  (1.3:1).** In the three-part share bar, adjacent parts do not reach 3:1 against each other
  (pink/grey 1.3, grey/white 2.5), so each part is separated by a background gap (each part is at
  least 7:1 against the page) and labelled with its count; nothing relies on colour alone.
- **Metallic finish:** the lighter band lives only in the plum panel's empty top strip and drifts
  toward the pointer (`js/metal.js`, eased, once per frame, skipped when off-screen); panel text sits
  below the strip, never on the moving highlight. Off for touch-only pointers and under
  prefers-reduced-motion.
- **Type:** self-hosted fonts under the SIL Open Font License (licence files in `site/fonts/`):
  Instrument Serif (large tight headlines), Inter (body), JetBrains Mono (run ids, code). The site
  makes no external requests (owner).
- **Layout:** large left-aligned serif headline in the hero, secondary-grey body, a pill badge
  with a plum tag above it, the rounded metallic plum feature panel on the right (pink letter-spaced
  label, very large serif number, short sentence), cards on #111111 with large radius and a
  hairline border, wide empty spacing. Under 640 px every table row becomes a card, with each value
  under its column name.
- **Interaction:** slight lift on hover and a soft glow on press, done with transforms only (no
  layout shift); all transitions off under prefers-reduced-motion.

## D32. Landing-page review fixes and the ASCII engine

**Owner decisions (2026-11-13):**
1. **Caveat on the landing page:** the full fixed sentence stays in the hero (anchor `#caveat`)
   and in "How this was measured". Under the tables in between it is one short grey line, "Built
   so that splitting can hurt. See the caveat.", linking to the hero box. The explorer and "try
   your own run" keep the full sentence under every table.
2. **"Lost at the merge" legend dot:** #8e6fa3, a muted plum-lavender: 4.7:1 on the page (a
   graphic needs 3:1), and the most distinct of the candidates from the pink, grey and white parts.
   It is always labelled; if a merge loss is ever non-zero it draws as its own bar segment.
3. **ASCII engine (`site/js/ascii.js`):** one sticky canvas in the right column beside "The ledger"
   through "The 3 no fix here recovers"; each section names a scene. **Every glyph is a real row of
   the run** (row number and line id or rate code), placed where the run put it:
   - ledger-whole: the 70 rows as one block;
   - scatter: the block splits into the four workers' real ranges (scatter = split);
   - dim: the workers that returned empty lists dim (dimming = empty-handed worker);
   - reform: the columns reform into one block, and only the rows of kept items stay lit (reform = merge);
   - rescatter: R4's real ranges, with the rate table copied to every worker, and R4's kept rows lit;
   - apart: each far pair's two rows light up pink, in different columns.

   Glyphs dissolve and scatter on the way (flickering through `·:;+=*#%`) and settle on their
   targets; glyphs near the pointer drift away and re-form after it passes; a faint dot field
   behind the canvas moves at 0.12 times the scroll speed (parallax), as a CSS layer.
4. **SITE_RULES compliance:**
   - The canvas sits in its own column and never over text.
   - Below 1000 px the canvas is dropped (`display: none`) and the engine does no work.
   - Under prefers-reduced-motion each scene is drawn once as a still frame; no transitions, no
     pointer effect, no parallax. Measured: 0 animation frames run, even with the pointer over the stage.
   - The loop runs only while something moves and the stage is on screen; it pauses when the tab
     is hidden; scroll and pointer listeners are passive.
5. **Performance (measured, headless Chrome with software rendering, pointer sweeping the stage and
   the page scrolling through scene changes):**

   | CPU speed | median frame | p95 frame | engine cost per frame |
   |---|---|---|---|
   | normal | 16.7 ms | 16.8 ms | 2.5 ms |
   | 2x slower | 16.7 ms | 33.2 ms | 3.6 ms |
   | 4x slower | 16.7 ms | 50.1 ms | 7.0 ms |

   Settled rows are drawn as one cached image each (about 100 draws per frame instead of 1,020),
   and the dot field is a compositor layer. **Lite mode:** if animation frames run long (median
   over 24 ms across 40 frames), rows move as whole rows during transitions (no per-letter
   scatter or flicker); the scenes and what they show do not change. With the engine turned off
   (`?noascii`, diagnostics only), the same page holds 16.7 ms at 4x slower, so the engine is the cost.
6. **Tools:** `tools/shoot.mjs` (viewport screenshots, reduced motion, CPU throttling, frame
   timing) and `tools/check_mobile.mjs` (page width at 360 px and full-page captures).
