# Run file format (schema_version 1)

One JSON file per run. It is the input to `autopsy` and the website's data source.
Machine-readable schema: [schema/run.schema.json](schema/run.schema.json). Extra fields are allowed.

The autopsy reads only the **generic** fields marked ★. Any multi-agent run that fills them can
be autopsied, whatever the task: items are opaque string ids with an optional integer value.

## Top level

| Field | Meaning |
|---|---|
| `schema_version` ★ | Always `1` for this format. |
| `run_id` ★ | `<task_id>__<model>__w<workers>__t<temperature>`. |
| `created_utc` | When the run file was written. |
| `config` ★ | `model`, `endpoint`, `temperature`, `reasoning_effort` (null = provider default), `workers` (W), `max_tokens`, `itpm`. |
| `task` | Task-specific detail. For the ledger: `family`, `task_id`, `size`, `seed`, `n_lines`, `n_planted`, `task_text`, `columns`, `rows` (each with `row`, `line_id`, `qty`, `unit_rate_cents`, `paid_cents`). |
| `items` ★ | `universe`: every item id in the task. `key`: the items a perfect answer lists, each `{id, value}`. `value_unit`: unit of `value` (`cents` for the ledger shortfall). |
| `swarm` ★ | `planner`, `workers`, `merger` (below). |
| `baseline` ★ | Single-agent run on the same task (below). |
| `usage` | Calls, prompt and completion tokens, summed latency, for `swarm` and `baseline`. |

## Item

`{"id": "RX-4L4GJ", "value": 37231}`. `value` is null when the model gave no usable number.
Ids are compared case-insensitively with whitespace trimmed.

## Stage status

Every stage has `status`:
`ok` | `unparseable` (reply had no usable JSON) | `truncated` (reply cut off by the output
cap, `finish_reason` = `length`) | `call_failed` (non-retryable API error) |
`rejected_too_large` (provider refused the request size) | `not_called`.

## swarm

- `planner`: `call`, `status`, `briefs_used`, `parse_notes` (briefs ignored past W, ranges clamped or dropped).
- `workers[]` ★: `worker` (1-based), `brief`, `ranges` (inclusive row ranges), `slice` (item ids the worker was shown), `reported` (items it returned), `call`, `status`, `parse_notes`. A worker whose status is not `ok` has `reported: []`.
- `merger` ★: `call`, `status`, `final` (the swarm's answer), `parse_notes`.

## baseline

`call`, `status`, `final`, `parse_notes`. **`final` is null when the baseline was not scored**
(for example `rejected_too_large`: the task did not fit in one call). Null never means a score
of zero; `call.requested_tokens` and `call.limit_tokens` record the measured size and the limit.

## call

`prompt` (exact text sent), `raw_text`, `reasoning`, `finish_reason`, `prompt_tokens`,
`completion_tokens`, `latency_ms`, `retries`, `cached`, `error`, `rejected_too_large`,
and when rejected: `requested_tokens`, `limit_tokens`.
