// Landing story. One run tells it (STORY_RUN, seed 1 at W=4); every number is computed by
// autopsy.js from that run, its replays and the other run files. Nothing here is typed in.
import { autopsy, BUCKET_LABEL, LOSS_BUCKETS, pct, noSplit } from "./autopsy.js";
import { loadAll, replaysByOriginal, loadProvenance } from "./data.js";
import { el, table, caveat, nav, footer, REPO_URL } from "./ui.js";
import { startMetal } from "./metal.js";
import { startAscii } from "./ascii.js";

const STORY_RUN = "runs/ledgerctx-S-s1__openai_gpt-oss-120b__w4__t0.0.json";
const OLD_LEDGER_RUN = "runs/ledger-S-s1__gemini-3.8-flash__w4__t0.0.json";
const SWARMBENCH = "https://acyclic.dev/benchmark";
const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"];
const word = (n) => WORDS[n] ?? String(n);
const Word = (n) => { const w = word(n); return w[0].toUpperCase() + w.slice(1); };
const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
const andList = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

function section(id, scene, heading, ...body) {
  return el("section", { id, class: "story", "data-scene": scene, "aria-labelledby": `${id}-h` },
    el("h2", { id: `${id}-h` }, heading), ...body);
}

/** Owner (D32): between the hero and the method section, a short grey line replaces the caveat box. */
function shortCaveat() {
  return el("p", { class: "caveat-short" }, "Built so that splitting can hurt. ", el("a", { href: "#caveat" }, "See the caveat."));
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

/** Everything the ASCII stage draws, read from the run (and its R1 and R5 replays). */
function buildAsciiModel(run, a, r4run, r4a, r5run, r5a) {
  const upper = (x) => String(x).toUpperCase();
  const rows = run.task.rows.map((r) => {
    const id = upper(r.line_id || r.id);
    const rate = !r.line_id;
    const text = rate ? `${String(r.row).padStart(2)} ${r.rate_code}` : `${String(r.row).padStart(2)} ${r.line_id}`;
    return { id, rate, text };
  });
  const cols = (wk) => wk.map((w) => w.slice.map(upper));
  const kept = (aa) => {
    const ids = new Set();
    for (const p of aa.swarm.per_item) if (p.bucket === "kept") for (const n of p.needs) if (!n.startsWith("RATE:")) ids.add(n);
    return ids;
  };
  const farRows = new Set(), farPairs = [];
  let farSplit = 0;
  for (const p of a.swarm.per_item) {
    if (p.type !== "far pair") continue;
    p.needs.forEach((n) => farRows.add(n));
    farPairs.push(p.needs);
    if (!p.complete_in.length) farSplit++;
  }
  // captions under the canvas: every number comes from the run (D33)
  const W = run.swarm.workers.length;
  const holders = (wk) => wk.filter((w) => w.slice.some((i) => String(i).startsWith("RATE:"))).map((w) => w.worker);
  const h0 = holders(run.swarm.workers);
  const empty = run.swarm.workers.filter((w) => w.reported.length === 0).map((w) => w.worker);
  const finalKey = a.swarm.score.true_positives;
  const wList = (xs) => (xs.length < 2 ? `worker ${xs.join("")}` : `workers ${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
  const captions = {
    "ledger-whole": `${run.task.rows.length} rows, as the single agent sees them`,
    scatter: `the planner's ${W} blocks; ` + (h0.length === 1 ? `only worker ${h0[0]} holds the rate table` : `${h0.length} of ${W} workers hold the rate table`),
    dim: `dimmed: ${wList(empty)}, which returned an empty list`,
    reform: `lit: the ${finalKey} item${finalKey === 1 ? "" : "s"} in the final answer`,
    apart: farSplit === farPairs.length ? `pink: each duplicate claim's two rows, in different workers`
      : `pink: the ${farPairs.length} duplicate claims' rows; ${farSplit} split across workers`,
  };
  if (r4run) { // (the replay passed in is R1 since D35)
    const h4 = holders(r4run.swarm.workers), n4 = r4run.swarm.workers.length;
    captions.rescatter = (h4.length === n4 ? "every worker given the rate table" : `${h4.length} of ${n4} workers given the rate table`) +
      `: ${r4a.swarm.score.true_positives} of ${a.swarm.key_count} found`;
  }
  if (r5run) {
    const h5 = holders(r5run.swarm.workers), n5 = r5run.swarm.workers.length;
    captions.r5 = "R5: " + (h5.length === n5 ? "every worker given the rate table" : `${h5.length} of ${n5} workers given the rate table`) +
      `, blocks by position: ${r5a.swarm.score.true_positives} of ${a.swarm.key_count} found`;
  }
  return {
    captions, farPairs,
    rows,
    columns: cols(run.swarm.workers),
    emptyWorkers: run.swarm.workers.map((w, i) => (w.reported.length === 0 ? i : -1)).filter((i) => i >= 0),
    kept: kept(a),
    columnsR4: r4run ? cols(r4run.swarm.workers) : null,
    keptR4: r4a ? kept(r4a) : null,
    columnsR5: r5run ? cols(r5run.swarm.workers) : null,
    keptR5: r5a ? kept(r5a) : null,
    farRows,
  };
}

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
  const reps = replaysByOriginal(data.replays); // R1-R4
  const repsAll = replaysByOriginal([...data.replays, ...data.guidance]); // R1-R5 (D38)
  const provenance = await loadProvenance();
  const run = byPath.get(STORY_RUN);
  const a = autopsy(run);
  const s = a.swarm, base = a.baseline, K = s.key_count, W = run.config.workers, t = run.task;
  const counts = t.counts;
  const workers = run.swarm.workers;
  const emptyWorkers = workers.filter((w) => w.reported.length === 0).map((w) => w.worker);
  const tableHolders = workers.filter((w) => w.slice.some((i) => String(i).startsWith("RATE:"))).map((w) => w.worker);
  const storyReps = (repsAll.get(run.run_id) || []).map((r) => r.run);
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
  const heroCaveat = caveat(run);
  if (heroCaveat) heroCaveat.id = "caveat";
  parts.push(el("section", { id: "hero", class: "story hero", "aria-labelledby": "hero-h" },
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
        B.dropped_at_merge ? share(B.dropped_at_merge, "s-lav") : null, kept ? share(kept, "s-white") : null),
      el("ul", { class: "sharelegend" },
        el("li", {}, el("i", { class: "s-pink" }), "lost in the split ", el("b", {}, String(lostSplit))),
        el("li", {}, el("i", { class: "s-grey" }), "lost in workers ", el("b", {}, String(lostWorker))),
        el("li", {}, el("i", { class: "s-lav" }), "lost at the merge ", el("b", {}, String(B.dropped_at_merge))),
        el("li", {}, el("i", { class: "s-white" }), "kept ", el("b", {}, String(kept))))),
    heroCaveat));

  // 1. The task (sections 1-6 go into the ASCII track, see below)
  const trackStart = parts.length; // index the "task" section is about to take
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
    shortCaveat()));

  // 4. The merge
  parts.push(section("merge", "reform", "The merge kept everything it was given",
    el("p", {}, `The merger's final answer has ${s.score.final_count} item${s.score.final_count === 1 ? "" : "s"}: ${s.score.true_positives} correct, ${s.score.final_count - s.score.true_positives} wrong. ` +
      (dropped === 0 ? `In all ${word(fam2A.length)} runs of this task on this model, the merger dropped no item a worker had reported.`
        : `Across ${fam2A.length} runs the merger dropped ${dropped} reported items.`)),
    el("p", {}, "So every point this swarm lost was lost before the merge: in the split, or in a worker.")));

  // 5. The fix that holds on every seed (D35): R1 per seed at the story's W, R4 beside it.
  if (r4) {
    const sentence = r4.run.replay.change.replace(/^.*?sentence: /, "");
    const holdsTable = (wk) => wk.filter((w) => w.slice.some((i) => String(i).startsWith("RATE:"))).map((w) => w.worker);
    const found = (r) => autopsy(r).swarm.score.true_positives;
    // every original run at the story's worker count, with its R1 and R4 replays
    const seedsAtW = fam2A.filter((x) => x.run.config.workers === W).sort((p, q) => p.run.task.seed - q.run.task.seed)
      .map((x) => {
        const list = (reps.get(x.run.run_id) || []).map((r) => r.run);
        return { seed: x.run.task.seed, orig: x.a.swarm.score.true_positives,
          r1: list.find((q) => q.replay.label === "R1"), r4: list.find((q) => q.replay.label === "R4") };
      }).filter((x) => x.r1 && x.r4);
    const r1Found = seedsAtW.map((x) => found(x.r1)), r4Found = seedsAtW.map((x) => found(x.r4));
    const seedList = andList(seedsAtW.map((x) => x.seed));
    const same = r1Found.every((n) => n === r1Found[0]);
    const headline = same && seedsAtW.length > 1
      ? `Give every worker the rate table: ${r1Found[0]} of ${K} on ${seedsAtW.length === 3 ? "all three" : "every"} seed${seedsAtW.length > 1 ? "s" : ""}`
      : `Give every worker the rate table: ${andList(r1Found)} of ${K}`;
    // one plain sentence per seed where the planner sentence did worse than the table
    const r4Notes = seedsAtW.filter((x) => found(x.r4) < found(x.r1)).map((x) => {
      const h = holdsTable(x.r4.swarm.workers), n = x.r4.swarm.workers.length;
      const empty = x.r4.swarm.workers.filter((w) => w.reported.length === 0).length;
      const who = noSplit(x.r4) ? `gave every worker all ${x.r4.items.universe.length} rows`
        : h.length === n ? "gave every worker the rate table"
        : `still gave the rate table to ${h.length === 1 ? `worker ${h[0]} only` : `${h.length} of ${n} workers`}`;
      const what = empty === n ? `all ${word(n)} workers returned empty lists` : `${empty} of ${n} workers returned empty lists`;
      return `In seed ${x.seed}, the planner ${who}, and ${what}.`;
    });
    const totalReps = fam2.length * 4;
    const otherRuns = fam2A.filter((x) => x.run.config.workers !== W && reps.has(x.run.run_id))
      .sort((p, q) => p.run.config.workers - q.run.config.workers || p.run.task.seed - q.run.task.seed);
    parts.push(section("truth", "rescatter", headline,
      el("p", {}, `Replay R1 keeps the planner's blocks and briefs and adds the rate-table rows to every worker's slice; nothing else changes. ` +
        `At W=${W} the swarm then finds ${andList(r1Found)} of ${K} on seeds ${seedList}, against ${andList(seedsAtW.map((x) => x.orig))} in the original runs.`),
      table(["Seed", "Original run", "R1: rate table to every worker", "R4: one sentence to the planner"],
        seedsAtW.map((x) => [`seed ${x.seed}`, `${x.orig} of ${K}`, `${found(x.r1)} of ${K}`,
          `${found(x.r4)} of ${K}${noSplit(x.r4) ? " (no split: a worker held every row)" : ""}`])),
      el("p", {}, "The first fix tried was one sentence added to the planner's prompt:"),
      el("blockquote", {}, sentence),
      el("p", {}, `It finds ${andList(r4Found)} of ${K} on seeds ${seedList}` +
        // the "only when" clause is printed only if every seed bears it out
        (seedsAtW.every((x) => (holdsTable(x.r4.swarm.workers).length === x.r4.swarm.workers.length) === (found(x.r4) >= found(x.r1)))
          ? ": it matches the table fix only when the planner responds by handing every worker the table. " : ". ") + r4Notes.join(" ")),
      el("p", { class: "note" }, `The story above is one run: seed ${t.seed} at W=${W}. This section shows all ${word(seedsAtW.length)} seeds at W=${W}; `,
        el("a", { href: "#nine" }, "the nine-run table"), ` has every setting. Replays done: ${data.replays.length} of ${totalReps}.`),
      otherRuns.length ? table(["Other run", "R1", "R2", "R3", "R4"], otherRuns.map((x) => {
        const list = reps.get(x.run.run_id).map((r) => r.run);
        return [`seed ${x.run.task.seed}, W=${x.run.config.workers} (original ${x.a.swarm.score.true_positives} of ${K})`,
          ...["R1", "R2", "R3", "R4"].map((l) => {
            const r = list.find((q) => q.replay.label === l);
            if (!r) return "not yet";
            return `${found(r)} of ${K}${noSplit(r) ? " (no split: a worker held every row)" : ""}`;
          })];
      }), { caption: `Replays at the other worker counts` }) : null,
      shortCaveat()));

    // 5b. Acyclic's own delegation text as planner guidance (R5, D37/D38). Items found only.
    const r5Of = (x) => (repsAll.get(x.run.run_id) || []).map((r) => r.run).find((q) => q.replay.label === "R5");
    const r5All = fam2A.map((x) => ({ x, r5: r5Of(x) })).filter((y) => y.r5)
      .sort((p, q) => p.x.run.config.workers - q.x.run.config.workers || p.x.run.task.seed - q.x.run.task.seed)
      .map((y) => ({ ...y, a5: autopsy(y.r5) }));
    if (r5All.length) {
      const n5 = r5All.length, allRuns = n5 === fam2A.length;
      const f5 = r5All.map((y) => y.a5.swarm.score.true_positives);
      const lo = Math.min(...f5), hi = Math.max(...f5);
      const span = lo === hi ? `${lo}` : hi - lo === 1 ? `${lo} or ${hi}` : `${lo} to ${hi}`;
      const g = r5All[0].r5.replay.guidance;
      const sentences = g.text.trim().split(/(?<=\.)\s+/);
      const quoted = sentences.find((x) => x.startsWith("Give children")) || g.text.trim();
      const prov = provenance && provenance.git_blob === g.git_blob && r5All.every((y) => y.r5.replay.guidance.git_blob === g.git_blob)
        ? provenance : null;
      const every = (pred) => r5All.every(pred);
      const tableToAll = every((y) => holdsTable(y.r5.swarm.workers).length === y.r5.swarm.workers.length);
      const neverWhole = every((y) => !noSplit(y.r5));
      const emptyW = r5All.flatMap((y) => y.r5.swarm.workers.filter((w) => w.reported.length === 0).map((w) => ({ y, w })));
      const emptyHeldNothing = emptyW.every(({ y, w }) => !y.a5.swarm.per_item.some((p) => p.complete_in.includes(w.worker)));
      const returnedNothing = r5All.reduce((n, y) => n + y.a5.swarm.buckets.holder_returned_nothing, 0);
      const farOf = (y) => y.a5.swarm.score.by_type["far pair"];
      const farTotal = farOf(r5All[0]).total;
      const farFound = r5All.reduce((n, y) => n + farOf(y).found, 0);
      const farAllSplit = every((y) => y.a5.swarm.per_item.filter((p) => p.type === "far pair").every((p) => p.bucket === "evidence_split"));
      // "by position": each worker's line-item rows are one unbroken block of the ledger
      const byPosition = every((y) => y.r5.swarm.workers.every((w) => {
        const rows = w.slice.filter((i) => !String(i).startsWith("RATE:"))
          .map((i) => y.r5.task.rows.find((r) => r.line_id === i)).filter(Boolean).map((r) => r.row);
        return !rows.length || Math.max(...rows) - Math.min(...rows) + 1 === rows.length;
      }));
      const r5AtW = seedsAtW.map((x) => ({ ...x, r5: r5All.find((y) => y.x.run.config.workers === W && y.x.run.task.seed === x.seed) }))
        .filter((x) => x.r5);
      const ws = [...new Set(r5All.map((y) => y.x.run.config.workers))];
      const seeds = [...new Set(r5All.map((y) => y.x.run.task.seed))].sort((p, q) => p - q);
      const sourceLink = prov ? `${prov.source_url}/blob/${prov.source_commit}/${prov.source_path}` : null;
      const facts = [];
      if (tableToAll) facts.push(`In ${allRuns ? "all " : ""}${word(n5)} runs the new planner gave every worker the rate table` +
        (neverWhole ? ", and never gave one worker every row." : "."));
      if (returnedNothing === 0) facts.push(emptyW.length === 0 ? "No worker returned an empty list."
        : `No item was lost to a worker returning nothing: ${emptyW.length} of ${r5All.reduce((n, y) => n + y.r5.swarm.workers.length, 0)} workers returned empty lists` +
          (emptyHeldNothing ? ", and none of them held a whole item." : "."));
      if (farFound === 0) facts.push(`Far pairs stayed at 0 of ${farTotal} in ${allRuns ? "all " : ""}${word(n5)} runs` +
        (byPosition && farAllSplit ? `, because the split is still by position: each worker got one block of consecutive line items, so each pair's two rows, at least half the ledger apart, went to different workers.` : "."));
      parts.push(section("acyclic", "r5", `Acyclic's own delegation sentence: ${span} of ${K} in ${allRuns ? "all " : ""}${word(n5)} runs`,
        el("p", { class: "plain-limit" }, "This tests their guidance sentence in this harness, not their system. In Acyclic's harness a child can read the parent's files; here a worker sees only its brief and its rows."),
        el("p", {}, `Replay R5 appends Acyclic Labs' delegation guidance, verbatim, to the planner's prompt under a line "Delegation guidance:". A new planner splits the ledger; workers and merger then run as before. The guidance includes this sentence:`),
        el("blockquote", {}, quoted),
        el("p", { class: "muted source" }, prov
          ? ["From ", el("a", { href: sourceLink }, prov.source_path), ` in ${prov.source_repo}, commit ${prov.source_commit.slice(0, 7)}, licensed ${prov.licence}. The full ${prov.bytes}-byte text is used unmodified (`,
            el("a", { href: `${REPO_URL}/blob/main/${prov.file}` }, prov.file), ")."]
          : `From ${g.file}, ${g.bytes} bytes, used unmodified.`),
        el("details", {}, el("summary", {}, "The full guidance text"), el("p", { class: "guidance-text" }, g.text.trim())),
        r5AtW.length ? table(["Seed", "Original run", "R1: rate table to every worker", "R5: Acyclic's guidance"],
          r5AtW.map((x) => [`seed ${x.seed}`, `${x.orig} of ${K}`, `${found(x.r1)} of ${K}`,
            `${x.r5.a5.swarm.score.true_positives} of ${K}`]), { caption: `At W=${W}, items found` }) : null,
        table(["Workers", ...seeds.map((sd) => `Seed ${sd}`)], ws.map((w) => [`W=${w}`, ...seeds.map((sd) => {
          const y = r5All.find((q) => q.x.run.config.workers === w && q.x.run.task.seed === sd);
          return y ? `${y.a5.swarm.score.true_positives} (${y.x.a.swarm.score.true_positives})` : "not run";
        })]), { caption: `R5 in ${allRuns ? "all " : ""}${word(n5)} runs: items found of ${K}, the original run in brackets` }),
        facts.length ? el("ul", {}, facts.map((f) => el("li", {}, f))) : null,
        el("p", {}, "How each R5 brief reads, by a judge model, is in the ",
          el("a", { href: `explorer.html?run=${encodeURIComponent(run.run_id)}` }, "run explorer"), "."),
        shortCaveat()));
    }

    // 6. The far pairs
    const far = (x) => x.a.swarm.score.by_type["far pair"];
    const all = [{ a }, ...[...repA.values()]];
    const farLost = Math.min(...all.map((x) => far(x).total - far(x).found));
    const fresh = ["R4", "R5"].filter((l) => repA.has(l)); // replays with a new planner call
    const newPlanners = andList(fresh);
    const newHolders = fresh.reduce((n, l) => n + repA.get(l).a.swarm.per_item.filter((p) => p.type === "far pair" && p.complete_in.length).length, 0);
    const r5Runs = fam2A.map((x) => (repsAll.get(x.run.run_id) || []).map((r) => r.run).find((q) => q.replay.label === "R5"))
      .filter(Boolean).map((r) => ({ a: autopsy(r) }));
    parts.push(section("pairs", "apart", `The ${farLost} no fix here recovers`,
      el("p", {}, `The ${far({ a }).total} far pairs: one claim billed twice, on rows at least half the ledger apart. Only a worker holding both rows can see the duplicate.`),
      el("p", {}, `Far pairs found: ${far({ a }).found} of ${far({ a }).total} in the original run, and ` +
        ["R1", "R2", "R3", "R4", "R5"].filter((l) => repA.has(l)).map((l) => `${far(repA.get(l)).found} in ${l}`).join(", ") + ". " +
        `R1 to R3 keep the planner's blocks of rows; in ${newPlanners} the new planner again cut the line items into blocks, and ${newHolders === 0 ? "no worker held both rows of any far pair" : `${newHolders} far pair(s) had both rows with one worker`}.` +
        (r5Runs.length ? ` Across ${r5Runs.length === fam2A.length ? "all " : ""}${word(r5Runs.length)} R5 runs, far pairs found: ${r5Runs.reduce((n, y) => n + far(y).found, 0)} of ${r5Runs.reduce((n, y) => n + far(y).total, 0)}.` : ""))));
  }

  // Sections 1-6 share one sticky ASCII stage on the right (D32). It draws the run's real rows.
  const trackSections = parts.splice(trackStart, parts.length - trackStart);
  const stage = el("div", { class: "track-stage", "aria-hidden": "true" },
    el("canvas", { class: "ascii-canvas" }), el("p", { class: "ascii-caption" }));
  parts.push(el("div", { class: "track" }, el("div", { class: "track-text" }, trackSections), stage));
  const r1 = repA.get("R1"), r5 = repA.get("R5");
  const asciiModel = buildAsciiModel(run, a, r1 ? r1.run : null, r1 ? r1.a : null, // section 5 shows R1 (D35)
    r5 ? r5.run : null, r5 ? r5.a : null); // section 5b shows R5 (D38)

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
    shortCaveat()));

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
  if (!new URLSearchParams(location.search).has("noascii")) startAscii(stage, asciiModel, trackSections); // ?noascii: diagnostics only
}

main();
