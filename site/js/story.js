// Landing story. One run tells it (STORY_RUN, seed 1 at W=4); every number is computed by
// autopsy.js from that run, its replays and the other run files. Nothing here is typed in.
import { autopsy, BUCKET_LABEL, LOSS_BUCKETS, pct, noSplit } from "./autopsy.js";
import { loadAll, replaysByOriginal } from "./data.js";
import { el, table, caveat, nav, footer } from "./ui.js";
import { startMetal } from "./metal.js";

const STORY_RUN = "runs/ledgerctx-S-s1__openai_gpt-oss-120b__w4__t0.0.json";
const OLD_LEDGER_RUN = "runs/ledger-S-s1__gemini-3.8-flash__w4__t0.0.json";
const SWARMBENCH = "https://acyclic.dev/benchmark";
const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"];
const word = (n) => WORDS[n] ?? String(n);
const Word = (n) => { const w = word(n); return w[0].toUpperCase() + w.slice(1); };
const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
const andList = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

function section(id, scene, heading, ...body) {
  return el("section", { id, class: "story", "aria-labelledby": `${id}-h` },
    el("div", { class: "ascii", "data-scene": scene, "aria-hidden": "true" }),
    el("h2", { id: `${id}-h` }, heading), ...body);
}

function rowsText(w) {
  return w.ranges.map(([a, b]) => `${a}–${b}`).join(" and ");
}

const SHORT = {
  never_assigned: "no worker was given its row",
  context_not_passed: "the worker holding its row was not given the rate-table row it needs",
  evidence_split: "its two rows went to different workers",
  assigned_unreached: "the worker's reply was cut off before reaching it",
  holder_returned_nothing: "the worker holding everything it needs returned an empty list",
  holder_answered_missed: "the worker holding it answered, but not with this item",
  dropped_at_merge: "a worker reported it and the merger left it out",
};

async function main() {
  document.body.prepend(nav("index.html"));
  const main = document.getElementById("main");
  let data;
  try {
    data = await loadAll();
  } catch (e) {
    main.replaceChildren(el("p", {}, `Could not load run files: ${e.message}`));
    return;
  }
  const byPath = new Map(data.runs.map((r) => [r.path, r.run]));
  const reps = replaysByOriginal(data.replays);
  const run = byPath.get(STORY_RUN);
  const a = autopsy(run);
  const s = a.swarm, base = a.baseline, K = s.key_count, W = run.config.workers, t = run.task;
  const counts = t.counts;
  const workers = run.swarm.workers;
  const emptyWorkers = workers.filter((w) => w.reported.length === 0).map((w) => w.worker);
  const tableHolders = workers.filter((w) => w.slice.some((i) => String(i).startsWith("RATE:"))).map((w) => w.worker);
  const storyReps = (reps.get(run.run_id) || []).map((r) => r.run);
  const repA = new Map(storyReps.map((r) => [r.replay.label, { run: r, a: autopsy(r) }]));
  const r4 = repA.get("R4");

  // All family-2 original runs on this model, for the nine-run table and the merge claim.
  const fam2 = data.runs.map((r) => r.run).filter((r) => r.task.family === t.family && r.config.model === run.config.model);
  const fam2A = fam2.map((r) => ({ run: r, a: autopsy(r) }));
  const dropped = fam2A.reduce((n, x) => n + x.a.swarm.buckets.dropped_at_merge, 0);

  const parts = [];

  // 0. Hero: headline left, metallic feature panel right, a three-part share bar below.
  const B = s.buckets;
  const lostSplit = B.never_assigned + B.context_not_passed + B.evidence_split;
  const lostWorker = B.assigned_unreached + B.holder_returned_nothing + B.holder_answered_missed;
  const kept = B.kept;
  const share = (n, cls) => el("span", { class: cls, style: `flex:${n} 1 0` });
  parts.push(el("section", { id: "hero", class: "story hero", "aria-labelledby": "hero-h" },
    el("div", { class: "ascii", "data-scene": "ledger-whole", "aria-hidden": "true" }),
    el("div", { class: "hero-text" },
      el("p", { class: "badge-pill" }, el("span", { class: "tag" }, "One run"),
        `seed ${t.seed} · ${W} workers · ${run.config.model}`),
      // non-breaking spaces keep "12 of 12" and "found 3" on one line
      el("h1", { id: "hero-h" }, `One agent found ${base.score.true_positives} of ${K}. ${Word(W)} agents found ${s.score.true_positives}.`),
      el("p", { class: "lede" }, `Same model, same ledger, same ${K} planted problems. swarm-autopsy takes one finished multi-agent run and puts every lost item in exactly one place: the split, a worker, or the merge.`)),
    el("aside", { class: "feature metal", "aria-label": "Items the swarm lost" },
      el("p", { class: "label" }, "Lost by the swarm"),
      el("p", { class: "big" }, String(s.lost)),
      el("p", {}, `of the ${K} planted problems never reached the swarm's final answer. The single agent, on the same ledger, missed ${K - base.score.true_positives}.`)),
    el("div", { class: "shares" },
      el("div", { class: "sharebar", role: "img",
        "aria-label": `${lostSplit} lost in the split, ${lostWorker} lost in workers, ${B.dropped_at_merge} lost at the merge, ${kept} kept, of ${K}` },
        lostSplit ? share(lostSplit, "s-pink") : null, lostWorker ? share(lostWorker, "s-grey") : null,
        kept ? share(kept, "s-white") : null),
      el("ul", { class: "sharelegend" },
        el("li", {}, el("i", { class: "s-pink" }), "lost in the split ", el("b", {}, String(lostSplit))),
        el("li", {}, el("i", { class: "s-grey" }), "lost in workers ", el("b", {}, String(lostWorker))),
        el("li", {}, "lost at the merge ", el("b", {}, String(B.dropped_at_merge))),
        el("li", {}, el("i", { class: "s-white" }), "kept ", el("b", {}, String(kept))))),
    caveat(run)));

  // 1. The task
  parts.push(section("task", "ledger-whole", `The ledger: ${t.n_lines} line items, a rate table of ${t.n_rate_codes}, ${K} planted problems`,
    el("p", {}, `A remittance ledger. Some lines carry their own unit rate; others carry only a rate code whose rate is in the table at the top. The task: find every underpaid line and every claim billed twice.`),
    el("ul", {},
      el("li", {}, `${counts.line} underpaid lines that can be judged alone`),
      el("li", {}, `${counts.context} underpaid lines that need the rate table`),
      el("li", {}, `${counts.far_pair} claims billed twice on rows at least half the ledger apart`),
      el("li", {}, `${counts.near_pair} claim billed twice on rows close together (a control)`)),
    el("p", {}, `Run by ${run.config.model}, temperature ${run.config.temperature}, reasoning effort ${run.config.reasoning_effort}. The single agent sees all ${t.n_rows} rows in one call and finds ${base.score.true_positives} of ${K}.`)));

  // 2. The split
  parts.push(section("split", "scatter", `The planner split it ${word(W)} ways`,
    el("p", {}, `The planner sees the task, the row count and the column headers, never the rows. It wrote ${W} briefs and gave each worker a block of rows.`),
    el("ol", {}, workers.map((w) => el("li", {},
      `Worker ${w.worker}: rows ${rowsText(w)} (${w.slice.length} rows${tableHolders.includes(w.worker) ? ", the rate table" : ""})`))),
    el("p", {}, tableHolders.length === 1 ? `Only worker ${tableHolders[0]} got the rate table.` : `${tableHolders.length} workers got the rate table.`,
      " Workers cannot see each other, yet these briefs rely on something the worker was not given:"),
    el("ul", { class: "quotes" }, ((run.annotations || {}).briefs || [])
      .filter((b) => b.relies_on_missing.answer === "yes" && b.relies_on_missing.quote)
      .map((b) => el("li", {}, `Worker ${b.worker}: `, el("q", {}, b.relies_on_missing.quote)))),
    el("p", { class: "muted" }, "Model-read annotations: a judge model's reading of each brief, checked by hand (DECISIONS D27). They never change a score."),
    el("p", {}, el("a", { href: `explorer.html?run=${encodeURIComponent(run.run_id)}` }, "Read every brief in the run explorer"))));

  // 3. Where the lost items went
  const lostRows = LOSS_BUCKETS.filter((b) => s.buckets[b]).map((b) => [BUCKET_LABEL[b], String(s.buckets[b]), SHORT[b]]);
  parts.push(section("lost", "dim", `Where the ${s.lost} went`,
    table(["Bucket", "Items", "What happened"], lostRows),
    el("p", {}, `Workers ${emptyWorkers.join(", ")} returned empty lists. ${s.buckets.dropped_at_merge === 0 ? "Nothing was lost at the merge." : ""}`),
    caveat(run)));

  // 4. The merge
  parts.push(section("merge", "reform", "The merge kept everything it was given",
    el("p", {}, `The merger's final answer has ${s.score.final_count} item${s.score.final_count === 1 ? "" : "s"}: ${s.score.true_positives} correct, ${s.score.final_count - s.score.true_positives} wrong. ` +
      (dropped === 0 ? `In all ${word(fam2A.length)} runs of this task on this model, the merger dropped no item a worker had reported.`
        : `Across ${fam2A.length} runs the merger dropped ${dropped} reported items.`)),
    el("p", {}, "So every point this swarm lost was lost before the merge: in the split, or in a worker.")));

  // 5. One sentence to the planner
  if (r4) {
    const sentence = r4.run.replay.change.replace(/^.*?sentence: /, "");
    const diff = r4.a.swarm.per_item.filter((p) => p.bucket === "kept").length - s.per_item.filter((p) => p.bucket === "kept").length;
    const repRows = ["R1", "R2", "R3", "R4"].filter((l) => repA.has(l)).map((l) => {
      const x = repA.get(l);
      return [`${l} ${x.run.replay.name}`, `${x.a.swarm.score.true_positives} of ${K}`, x.run.replay.change];
    });
    const totalReps = fam2.length * 4;
    const otherRuns = fam2A.filter((x) => x.run.run_id !== run.run_id && reps.has(x.run.run_id));
    parts.push(section("truth", "rescatter", `One sentence to the planner: ${r4.a.swarm.score.true_positives} of ${K}`,
      el("blockquote", {}, sentence),
      el("p", {}, `Added to the planner's prompt, nothing else changed: the swarm finds ${r4.a.swarm.score.true_positives} of ${K}, ${diff >= 0 ? "+" : ""}${diff} on the original run. ` +
        `This time the planner gave ${r4.run.swarm.workers.filter((w) => w.slice.some((i) => String(i).startsWith("RATE:"))).length} of ${r4.run.swarm.workers.length} workers the rate table.`),
      el("p", { class: "note" }, `These numbers are from one run: seed ${t.seed} at W=${W}. `,
        el("a", { href: "#nine" }, "The nine-run table"), " has all three seeds. ",
        `Replays of the other runs appear here as they land: ${data.replays.length} of ${totalReps} done.`),
      table(["Replay", "Found", "What changed"], repRows),
      otherRuns.length ? table(["Other run", ...["R1", "R2", "R3", "R4"]], otherRuns.map((x) => {
        const list = reps.get(x.run.run_id).map((r) => r.run);
        return [`seed ${x.run.task.seed}, W=${x.run.config.workers} (original ${x.a.swarm.score.true_positives} of ${K})`,
          ...["R1", "R2", "R3", "R4"].map((l) => {
            const r = list.find((q) => q.replay.label === l);
            if (!r) return "not yet";
            return `${autopsy(r).swarm.score.true_positives} of ${K}${noSplit(r) ? " (no split: a worker held every row)" : ""}`;
          })];
      }), { caption: "Replays of the other runs so far" }) : null,
      caveat(run)));

    // 6. The far pairs
    const far = (x) => x.a.swarm.score.by_type["far pair"];
    const all = [{ a }, ...[...repA.values()]];
    const farLost = Math.min(...all.map((x) => far(x).total - far(x).found));
    const r4Holders = r4.a.swarm.per_item.filter((p) => p.type === "far pair" && p.complete_in.length).length;
    parts.push(section("pairs", "apart", `The ${farLost} no fix here recovers`,
      el("p", {}, `The ${far({ a }).total} far pairs: one claim billed twice, on rows at least half the ledger apart. Only a worker holding both rows can see the duplicate.`),
      el("p", {}, `Far pairs found: ${far({ a }).found} of ${far({ a }).total} in the original run, and ` +
        ["R1", "R2", "R3", "R4"].filter((l) => repA.has(l)).map((l) => `${far(repA.get(l)).found} in ${l}`).join(", ") + ". " +
        `R1 to R3 keep the planner's blocks of rows; in R4 the new planner again cut the line items into blocks, and ${r4Holders === 0 ? "no worker held both rows of any far pair" : `${r4Holders} far pair(s) had both rows with one worker`}.`)));
  }

  // 7. Nine runs
  const byW = new Map();
  for (const x of fam2A) {
    if (!byW.has(x.run.config.workers)) byW.set(x.run.config.workers, []);
    byW.get(x.run.config.workers).push(x);
  }
  const nineRows = [...byW.keys()].sort((p, q) => p - q).map((w) => {
    const xs = byW.get(w).sort((p, q) => p.run.task.seed - q.run.task.seed);
    const per = (f) => xs.map(f);
    const pc = (vals) => `${pct(mean(vals))} (${vals.map((v) => pct(v).replace("%", "")).join("/")})`;
    const mb = (b) => mean(per((x) => x.a.swarm.buckets[b])).toFixed(1);
    return [`W=${w}`, pc(per((x) => x.a.baseline.score.recall)), pc(per((x) => x.a.swarm.score.recall)),
      mb("context_not_passed"), mb("evidence_split"), mb("holder_returned_nothing"), mb("holder_answered_missed"), mb("dropped_at_merge")];
  });
  parts.push(section("nine", "none", `Across ${word(fam2A.length)} runs`,
    el("p", {}, `Size ${[...new Set(fam2.map((r) => r.task.size))].join(", ")}; seeds ${andList([...new Set(fam2.map((r) => r.task.seed))].sort((p, q) => p - q))}; ${andList([...byW.keys()].sort((p, q) => p - q))} workers. Recall is the mean, with each seed in brackets; losses are the mean per run.`),
    table(["Workers", "Single agent recall", "Swarm recall", "Context not passed", "Evidence split", "Holder returned nothing", "Holder answered, missed", "Dropped at merge"], nineRows),
    caveat(run)));

  // 8. Independent lines
  const old = byPath.get(OLD_LEDGER_RUN);
  if (old) {
    const oa = autopsy(old).swarm;
    parts.push(section("alone", "none", "When every line stands alone, nothing is lost",
      el("p", {}, `A first ledger had only lines that can each be judged alone. On it, ${old.config.model} as a swarm of ${old.config.workers} found ${oa.score.true_positives} of ${oa.key_count}, with ${oa.lost} lost in any bucket (one run, size ${old.task.size}, seed ${old.task.seed}). Splitting hurts here only where a finding needs rows a worker was not given.`)));
  }

  // 9. Method
  parts.push(section("method", "none", "How this was measured",
    el("p", {}, `Every number on this page is computed in your browser from the run files in the repository, with the same rules as the Python autopsy; a test checks the two agree on every file. Nothing here is typed in.`),
    el("p", {}, "The comparison of a swarm with the same model working alone follows the shape of Acyclic Labs' public ",
      el("a", { href: SWARMBENCH }, "SwarmBench page"), "."),
    el("p", {}, "Prompts, sizes, scoring rules and every judgement call are written down in ",
      el("a", { href: "https://github.com/KinjalGoswami68/swarm-autopsy/blob/main/DECISIONS.md" }, "DECISIONS.md"), ". ",
      el("a", { href: "explorer.html" }, "Explore every run"), ", or ", el("a", { href: "try.html" }, "autopsy your own"), "."),
    caveat(run)));

  main.replaceChildren(...parts.filter(Boolean));
  document.body.append(footer());
  startMetal();
}

main();
