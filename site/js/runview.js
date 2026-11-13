// Renders one run: score, buckets, replays, workers with model-read annotations, item tracer.
// Every number is computed by autopsy.js from the run file(s) passed in.
import { autopsy, BUCKETS, LOSS_BUCKETS, BUCKET_LABEL, pct, noSplit, replayDiff } from "./autopsy.js";
import { el, table, caveat, frac } from "./ui.js";

const STAGE = { never_assigned: "split", context_not_passed: "split", evidence_split: "split",
  assigned_unreached: "worker", holder_returned_nothing: "worker", holder_answered_missed: "worker",
  dropped_at_merge: "merge", kept: "" };

function rowNumbers(run) {
  const m = new Map();
  for (const r of run.task.rows || []) {
    const id = (r.line_id || r.id || "").toUpperCase();
    if (id) m.set(id, r.row);
  }
  return m;
}

function hasRateTable(run, w) {
  return w.slice.some((i) => String(i).toUpperCase().startsWith("RATE:"));
}

function rangesText(w) {
  return w.ranges && w.ranges.length ? w.ranges.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(", ") : "none";
}

function scoreSection(run, a) {
  const s = a.swarm.score, b = a.baseline, K = a.swarm.key_count;
  const rows = [["Swarm (planner, workers, merger)", `${pct(s.recall)} (${frac(s.true_positives, K)})`,
    `${pct(s.precision)} (${frac(s.true_positives, s.final_count)})`,
    `${s.value_accuracy.accurate} of ${s.value_accuracy.found}`]];
  if ("score" in b) {
    const bs = b.score;
    rows.push(["Single agent (baseline)", `${pct(bs.recall)} (${frac(bs.true_positives, K)})`,
      `${pct(bs.precision)} (${frac(bs.true_positives, bs.final_count)})`,
      `${bs.value_accuracy.accurate} of ${bs.value_accuracy.found}`]);
  } else {
    rows.push(["Single agent (baseline)", `not scored (${b.status})`,
      b.requested_tokens ? `requested ${b.requested_tokens} ${b.limit_kind} tokens, limit ${b.limit_tokens}` : "", ""]);
  }
  const types = Object.keys(s.by_type);
  const typeRows = types.map((t) => [t, frac(s.by_type[t].found, s.by_type[t].total),
    "score" in b ? frac(b.score.by_type[t].found, b.score.by_type[t].total) : "n/a"]);
  return el("section", { "aria-labelledby": "h-score" },
    el("h2", { id: "h-score", text: "Score" }),
    table(["", "Recall", "Precision", "Shortfalls exact"], rows),
    types.length > 1 || types[0] !== "item"
      ? table(["Key item type", "Swarm found", "Single agent found"], typeRows) : null,
    caveat(run));
}

function bucketSection(run, a) {
  const s = a.swarm, K = s.key_count;
  const rows = BUCKETS.map((bk) => {
    const n = s.buckets[bk];
    const bar = el("span", { class: `bar ${bk === "kept" ? "bar-kept" : "bar-lost"}`,
      style: `width:${K ? (100 * n) / K : 0}%`, "aria-hidden": "true" });
    return { className: n ? "" : "zero",
      cells: [BUCKET_LABEL[bk], String(n), el("span", { class: "bar-track" }, bar)] };
  });
  return el("section", { "aria-labelledby": "h-buckets" },
    el("h2", { id: "h-buckets", text: `Where the ${s.lost} lost key items went` }),
    el("p", { class: "muted" }, `${K} key items. Each lands in exactly one bucket; the rules are in DECISIONS.md (D17, D22, D27).`),
    table(["Bucket", "Items", ""], rows, { class: "buckets" }),
    s.flags.length ? el("p", { class: "muted" }, "Flags: " + s.flags.join("; ")) : null,
    caveat(run));
}

function replaySection(run, a, replays) {
  if (!replays || !replays.length) return null;
  const head = ["Replay", "Recall", ...LOSS_BUCKETS.map((b) => BUCKET_LABEL[b].replace(/ \((split|worker|merge|reply cut off)\)$/, "")),
    "Recovered", "Newly lost", "Far pairs", "Near pairs", "Note"];
  const line = (label, r, ra) => {
    const bt = ra.swarm.score.by_type;
    const far = bt["far pair"] || { found: 0, total: 0 }, near = bt["near pair"] || { found: 0, total: 0 };
    const diff = r === run ? null : replayDiff(a.swarm, ra.swarm);
    const whole = noSplit(r);
    return { className: whole ? "no-split" : "", cells: [label,
      `${pct(ra.swarm.score.recall)} (${frac(ra.swarm.score.true_positives, ra.swarm.key_count)})`,
      ...LOSS_BUCKETS.map((b) => String(ra.swarm.buckets[b])),
      diff ? `+${diff.recovered.length}` : "", diff ? `−${diff.newly_lost.length}` : "",
      frac(far.found, far.total), frac(near.found, near.total),
      whole ? `no split: a worker held all ${r.items.universe.length} rows` : ""] };
  };
  const rows = [line("original", run, a), ...replays.map((r) => line(`${r.replay.label} ${r.replay.name}`, r, autopsy(r)))];
  return el("section", { "aria-labelledby": "h-replays" },
    el("h2", { id: "h-replays", text: "Replays (stage 2)" }),
    el("p", { class: "muted" }, "Each replay re-runs workers and merger with one thing changed; the baseline is the original's. ",
      "No merge replay: the merger dropped no reported item in any original run. ",
      "A far pair comes back only when both its rows land with one worker."),
    el("ul", { class: "muted" }, replays.map((r) => el("li", {}, `${r.replay.label}: ${r.replay.change}`))),
    table(head, rows, { class: "replays" }),
    caveat(run));
}

function markQuote(brief, quote) {
  if (!quote) return null;
  const canon = (t) => t.replace(/[‐-—−]/g, "-").replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"').replace(/[  ]/g, " ").toLowerCase();
  const q = canon(quote).replace(/\.$/, "");
  const i = canon(brief).indexOf(q);
  return i < 0 ? null : [i, i + q.length];
}

function workerSection(run, a) {
  const ann = new Map(((run.annotations || {}).briefs || []).map((b) => [b.worker, b]));
  const keyHeld = (w) => a.swarm.per_item.filter((p) => p.complete_in.includes(w.worker)).length;
  const cards = run.swarm.workers.map((w) => {
    const b = ann.get(w.worker);
    const quotes = b ? [b.relies_on_missing, b.limits_kinds].filter((x) => x && x.answer === "yes" && x.quote) : [];
    const spans = quotes.map((x) => markQuote(w.brief, x.quote)).filter(Boolean).sort((p, q) => p[0] - q[0]);
    const parts = [];
    let pos = 0;
    for (const [s, e] of spans) {
      if (s < pos) continue;
      parts.push(w.brief.slice(pos, s), el("mark", {}, w.brief.slice(s, e)));
      pos = e;
    }
    parts.push(w.brief.slice(pos));
    const annLine = (label, x) => el("li", {},
      `${label}: ${x.answer ?? "no answer"}`,
      x.answer === "yes" && x.quote ? el("q", {}, x.quote) : null,
      x.answer === "yes" && x.quote && !x.quote_verified ? el("span", { class: "badge" }, "quote not found in brief") : null);
    return el("article", { class: "worker" },
      el("h3", {}, `Worker ${w.worker}`),
      el("p", { class: "facts" },
        `Rows ${rangesText(w)} (${w.slice.length} rows${hasRateTable(run, w) ? ", including the rate table" : ""}) · `,
        `key items fully in slice: ${keyHeld(w)} · reported ${w.reported.length} · status ${w.status}`),
      el("p", { class: "brief" }, parts),
      b ? el("div", { class: "annotation" },
        el("p", { class: "label" }, "Model-read annotation: a judge model's reading of this brief. It never changes a score."),
        el("ul", {}, annLine("Relies on something the worker was not given", b.relies_on_missing),
          annLine("Limits the worker to some kinds of finding", b.limits_kinds))) : null);
  });
  return el("section", { "aria-labelledby": "h-workers" },
    el("h2", { id: "h-workers", text: "The planner's split and briefs" }),
    el("p", { class: "muted" }, `Planner status ${run.swarm.planner.status}; ${run.swarm.workers.length} briefs used.`),
    cards);
}

function explain(p, rowsOf) {
  const ws = (list) => (list.length ? `worker${list.length > 1 ? "s" : ""} ${list.join(", ")}` : "no worker");
  switch (p.bucket) {
    case "kept": return "It is in the swarm's final answer.";
    case "dropped_at_merge": return `${ws(p.reported_by)} reported it; the merger's final answer leaves it out.`;
    case "never_assigned": return "No worker was given its row.";
    case "context_not_passed": return `${ws(p.in_slices)} held part of what it needs, but no worker held its row together with the rate-table row it needs.`;
    case "evidence_split": return `Its rows (${rowsOf(p)}) were spread across ${ws(p.in_slices)}; no single worker held all of them.`;
    case "assigned_unreached": return `${ws(p.complete_in)} held every row it needs, but each reply was cut off before reaching it.`;
    case "holder_returned_nothing": return `${ws(p.complete_in)} held every row it needs and returned an empty list.`;
    case "holder_answered_missed": return `${ws(p.complete_in)} held every row it needs; at least one reported other items, but not this one.`;
    default: return "";
  }
}

function tracerSection(run, a) {
  const rowOf = rowNumbers(run);
  const items = a.swarm.per_item;
  const rowsOf = (p) => p.needs.map((n) => `${n.startsWith("RATE:") ? "rate " : ""}row ${rowOf.get(n) ?? "?"}`).join(", ");
  const baseFinal = run.baseline && run.baseline.final ? new Set(run.baseline.final.map((i) => String(i.id).toUpperCase())) : null;
  const out = el("div", { class: "trace", "aria-live": "polite" });
  const show = (id) => {
    const p = items.find((x) => x.id === id);
    out.replaceChildren(
      el("ol", {},
        el("li", {}, `Needs: ${rowsOf(p)}.`),
        el("li", {}, "Held by: ", p.needs.map((n) => {
          const holders = run.swarm.workers.filter((w) => w.slice.map((s) => String(s).toUpperCase()).includes(n)).map((w) => w.worker);
          return `${n.startsWith("RATE:") ? "rate row" : "row"} ${rowOf.get(n) ?? "?"} → ${holders.length ? "worker " + holders.join(", ") : "nobody"}`;
        }).join("; "), "."),
        el("li", {}, `All its rows together: ${p.complete_in.length ? "worker " + p.complete_in.join(", ") : "no worker"}.`),
        el("li", {}, `Reported by: ${p.reported_by.length ? "worker " + p.reported_by.join(", ") : "no worker"}.`),
        el("li", {}, `Merger: ${p.bucket === "kept" ? "kept it" : p.bucket === "dropped_at_merge" ? "dropped it" : "never saw it"}.`),
        el("li", {}, el("strong", {}, `${BUCKET_LABEL[p.bucket]}. `), explain(p, rowsOf)),
        el("li", {}, `Single agent: ${baseFinal === null ? "not scored" : baseFinal.has(p.id) ? "found it" : "missed it"}.`)));
  };
  const lost = items.filter((p) => p.bucket !== "kept"), kept = items.filter((p) => p.bucket === "kept");
  const select = el("select", { id: "trace-item", onchange: (e) => show(e.target.value) },
    el("optgroup", { label: "Lost" }, lost.map((p) => el("option", { value: p.id }, `${p.id} (${p.type})`))),
    el("optgroup", { label: "Kept" }, kept.map((p) => el("option", { value: p.id }, `${p.id} (${p.type})`))));
  if (items.length) show((lost[0] || kept[0]).id);
  return el("section", { "aria-labelledby": "h-trace" },
    el("h2", { id: "h-trace", text: "Follow one key item through the swarm" }),
    el("label", { for: "trace-item" }, "Key item "), select, out);
}

export function renderRun(container, run, replays = []) {
  const a = autopsy(run);
  container.replaceChildren(...[  // replaceChildren would turn a null into the text "null"
    el("header", { class: "run-head" },
      el("h1", {}, run.run_id),
      el("p", { class: "muted" }, `Model ${run.config.model} · temperature ${run.config.temperature} · reasoning ${run.config.reasoning_effort ?? "provider default"} · ${run.config.workers} workers`),
      caveat(run)),
    scoreSection(run, a), bucketSection(run, a), replaySection(run, a, replays),
    workerSection(run, a), tracerSection(run, a),
  ].filter(Boolean));
  return a;
}

export { STAGE };
