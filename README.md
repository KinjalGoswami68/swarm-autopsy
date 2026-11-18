# swarm-autopsy

**Where does a multi-agent run lose the points a single agent finds?** swarm-autopsy takes one
finished run of a planner → workers → merger swarm and puts every lost item in exactly one place:
the **split**, a **worker**, or the **merge**. Then it replays the run with one thing changed to see
how many items come back.

**Live site:** https://kinjalgoswami68.github.io/swarm-autopsy/ (story, run explorer, and a page
that autopsies your own run file in the browser).

> This family is built so that splitting can hurt; its numbers show the autopsy detects split and
> context failures, not how often swarms lose in general.

## The headline run

One task, one model (`openai/gpt-oss-120b` on Groq, temperature 0, low reasoning), a 70-row
remittance ledger with 12 planted problems. The first three points are seed 1 with 4 workers; the
replay points cover seeds 1, 2 and 3 with 4 workers:

- **The single agent found 12 of 12. The four-worker swarm found 3.**
- Where the 9 went: **4** context not passed (the worker holding the row was never given the
  rate table it needs), **3** evidence split across workers (a claim billed twice, its two rows
  given to different workers), **2** holder returned nothing (the worker held everything it
  needed and returned an empty list). **0** were lost at the merge.
- The planner gave the rate table to one worker and told the others to use "the rate-code map
  supplied by Worker 1", which no worker can receive.
- **Giving every worker the rate table** (replay R1: the planner's blocks and briefs unchanged,
  the rate-table rows added to every slice) brings the four-worker swarm to **9 of 12 on all three
  seeds** (originals: 3, 1 and 4).
- **One sentence added to the planner's prompt** ("Workers cannot communicate with each other,
  and each worker sees only its own rows.", replay R4) finds **9, 9 and 0** of 12 on the same
  three seeds. It matches the table fix only when the planner responds by handing every worker
  the table; in seed 3 the planner still gave the table to worker 1 only, and all four workers
  returned empty lists.
- **Acyclic Labs' own delegation guidance** (replay R5: their `delegation.md`, verbatim, appended
  to the planner's prompt; it includes "Give children self-contained briefs and clear ownership.")
  finds **8 or 9 of 12 in all nine runs** (seeds 1-3 × 2, 4 and 8 workers); at four workers 9, 8
  and 9. In all nine the new planner gave every worker the rate table, and no item was lost to a
  worker returning nothing. This tests their guidance sentence in this harness, not their system:
  in Acyclic's harness a child can read the parent's files; here a worker sees only its brief and
  its rows.
- The 3 far pairs come back in no replay: 0 of 3 at four workers in R1-R4 on every seed, and 0 of
  3 in all nine R5 runs. Every planner, old or new, splits the line items by position, so no
  worker ever holds both rows of a pair.

Across all nine runs (seeds 1-3 × 2, 4 and 8 workers), the single agent averages 86% recall and the
swarm 22-39%, and the merger never drops an item a worker reported. On a first ledger where every
line can be judged alone, a `gemini-3.8-flash` swarm lost nothing (one run); with `qwen/qwen3.8-27b`
at the smallest size, every item the swarm lost there was a worker miss, none in the split or
the merge. The run explorer shows every run, brief and replay.

## What it measures

For every key item, exactly one bucket (rules in [DECISIONS.md](DECISIONS.md), D17, D22, D27):

| Bucket | Stage | Meaning |
|---|---|---|
| never assigned | split | no worker was given its row |
| context not passed | split | a worker held its row but not the context row (rate table) it needs |
| evidence split across workers | split | its rows went to different workers; no one held them all |
| assigned, unreached | worker | the holder's reply was cut off before reaching it |
| assigned, holder returned nothing | worker | the holder of every needed row returned an empty list |
| assigned, holder answered, missed it | worker | the holder reported other items, not this one |
| found, dropped at merge | merge | a worker reported it; the final answer leaves it out |
| found and kept | – | not a loss |

Also reported: recall and precision for the swarm and the single agent, recall per item type,
false positives kept from workers or invented by the merger, and (from stage 2) replays:
**R1** rate table to every worker, **R2** neutral briefs, **R3** both, **R4** the planner told
that workers cannot communicate, **R5** Acyclic's delegation guidance appended to the planner's
prompt (any other guidance file works the same way, with `--planner-guidance`). Brief
annotations, made by a judge model and checked by hand, are shown as "why" and never change a score.

## Run it

Python 3.12+, and Node 22+ for the site tests, the preview server and the screenshot tools.

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows; on Linux/macOS: .venv/bin/pip
```

Keys go in `.env` (never committed): `GROQ_API_KEY` for Groq, `LLM_API_KEY` for any other
OpenAI-compatible endpoint (the default is Google AI Studio's, model `gemini-3.8-flash`). Every
call is cached in `cache/`, so re-running a command replays finished calls; a daily-quota error
stops the run cleanly, and the same command resumes later.

```
python cli.py generate --family ledger-ctx --sizes S --seeds 1        # tasks and answer keys
python cli.py run --family ledger-ctx --sizes S --seeds 1 2 3 --workers 4 \
    --model openai/gpt-oss-120b --endpoint https://api.groq.com/openai/v1 \
    --reasoning-effort low --tpm 8000 --max-tokens-total 8000 --rpd 1000
python cli.py table --model openai/gpt-oss-120b                       # summary, one row per size and W
python cli.py autopsy runs/<run file>.json                            # full autopsy of one run
python cli.py replay runs/<run file>.json                             # stage 2 replays R1-R4
python cli.py replay-table runs/<run file>.json
python cli.py replay runs/<run file>.json --replays R5                # Acyclic's delegation text (D37)
python cli.py replay runs/<run file>.json --replays --planner-guidance my-guidance.md   # any guidance file
python cli.py annotate runs/<run file>.json                           # model-read brief annotations
```

## Your own runs

A run file is one JSON document; [SCHEMA.md](SCHEMA.md) describes it and
[schema/run.schema.json](schema/run.schema.json) validates it. Any planner → workers → merger run
that fills the generic fields (key items, each worker's slice and report, the final answer) can be
autopsied, whatever the task. Drop it on the site's "Try your own run" page: it is checked and
autopsied in your browser, nothing is uploaded.

## The site

Plain HTML, CSS and JavaScript in `site/`, published by GitHub Actions on every push to `main`
after the tests pass. Every number on it is computed in the browser from the run files by
`site/js/autopsy.js`, a port of `autopsy.py`; a test runs both on every committed run file and
requires identical output.

```
python build_site.py --serve        # build _site/ and preview it on http://127.0.0.1:8000
python -m pytest -q                 # all tests, including the Python/JavaScript parity checks
node tools/check_mobile.mjs <outdir> <url>   # fails if a page is wider than a 360px phone
```

Design: [DESIGN.md](DESIGN.md) and [SITE_RULES.md](SITE_RULES.md). The ASCII art draws the run's
real rows; it is dropped on small screens and still under prefers-reduced-motion.

## Limits, stated plainly

- **Small samples.** Three seeds per setting, one task size for the main experiment. Read the
  tables as patterns, not measurements.
- **A task built to make splitting hurt.** The second ledger family plants items that need a rate
  table or two rows far apart. It shows the autopsy can find split and context failures; it does
  not show how often swarms lose in general.
- **Free tiers shaped the experiment.** Rs 0 budget. Groq's free limits on `qwen/qwen3.8-27b` cut
  replies off, so the first grid's larger sizes mostly measure an output cap (the "unreached"
  bucket exists for this). `gpt-oss-120b` runs at low reasoning because default reasoning did not
  fit Groq's 8,000 tokens per minute. Gemini's free tier allows 20 requests a day.
- **Answer-only prompts.** Every role is asked for the answer without visible working, to fit the
  output limits; arithmetic misses are expected to be higher than with working shown.
- **Temperature 0** for reproducibility; real swarms usually run warmer.

Every one of these choices, and every other judgement call, is in [DECISIONS.md](DECISIONS.md).

## Credit

The comparison of a swarm with the same model working alone follows the shape of Acyclic Labs'
public [SwarmBench page](https://acyclic.dev/benchmark).

Built by Kinjal Goswami.
