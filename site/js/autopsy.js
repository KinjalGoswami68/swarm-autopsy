// Port of autopsy.py (DECISIONS D17, D22, D27). Every number on the site is computed here from
// run files. tests/test_site_parity.py runs this file under Node on every committed run file and
// requires output identical to autopsy.py. Keep the two in step.

export const BUCKETS = ["never_assigned", "context_not_passed", "evidence_split", "assigned_unreached",
  "holder_returned_nothing", "holder_answered_missed", "dropped_at_merge", "kept"];
export const MISSED_BUCKETS = ["holder_returned_nothing", "holder_answered_missed"];
export const LOSS_BUCKETS = BUCKETS.slice(0, -1);
export const BUCKET_LABEL = {
  never_assigned: "never assigned (split)",
  context_not_passed: "context not passed (split)",
  evidence_split: "evidence split across workers (split)",
  assigned_unreached: "assigned, unreached (reply cut off)",
  holder_returned_nothing: "assigned, holder returned nothing (worker)",
  holder_answered_missed: "assigned, holder answered, missed it (worker)",
  dropped_at_merge: "found, dropped at merge (merge)",
  kept: "found and kept",
};
const VALUE_TOLERANCE = 1; // cents (D7)

const norm = (i) => String(i).trim().toUpperCase();
const ids = (items) => items.map((i) => norm(i.id));
const pyStr = (v) => (v === null || v === undefined ? "None" : String(v));
const pyList = (xs) => "[" + xs.join(", ") + "]";
const nonEmpty = (xs) => Array.isArray(xs) && xs.length > 0;

export function reachedIds(order, call, status) {
  if (status !== "truncated") return null;
  const raw = (((call || {}).raw_text) || "").toUpperCase();
  const ord = order.map(norm);
  const tokens = new Set(raw.match(/[A-Z0-9][A-Z0-9_-]*[A-Z0-9]|[A-Z0-9]/g) || []);
  let last = -1;
  ord.forEach((id, k) => { if (tokens.has(id)) last = k; });
  return new Set(ord.slice(0, last + 1));
}

export function bucketOf(item, slices, reportedSets, finalIds, reached, needs, context) {
  if (finalIds.has(item)) return "kept";
  if (reportedSets.some((rep) => rep.has(item))) return "dropped_at_merge";
  needs = (nonEmpty(needs) ? needs : [item]).map(norm);
  const ctx = new Set((context || []).map(norm));
  let own = needs.filter((n) => !ctx.has(n));
  if (!own.length) own = needs;
  reached = reached || slices.map(() => null);
  if (!slices.some((sl) => own.some((n) => sl.has(n)))) return "never_assigned";
  const complete = [];
  slices.forEach((sl, i) => { if (needs.every((n) => sl.has(n))) complete.push([reached[i], reportedSets[i]]); });
  if (!complete.length) {
    if (ctx.size && slices.some((sl) => own.every((n) => sl.has(n)))) return "context_not_passed";
    return "evidence_split";
  }
  const reaching = complete.filter(([r]) => r === null || needs.every((n) => r.has(n))).map(([, rep]) => rep);
  if (!reaching.length) return "assigned_unreached";
  if (reaching.every((rep) => rep.size === 0)) return "holder_returned_nothing";
  return "holder_answered_missed";
}

export function itemLabel(k) {
  const t = k.type || "item";
  return t === "pair" && k.subtype ? `${k.subtype} ${t}` : t;
}

const ratio = (a, b) => (b === 0 ? null : a / b);

function valueAccuracy(foundIds, reportedValues, keyValues) {
  const valued = foundIds.filter((i) => keyValues.get(i) !== null && keyValues.get(i) !== undefined);
  const ok = valued.filter((i) => reportedValues.get(i) !== null && reportedValues.get(i) !== undefined
    && Math.abs(reportedValues.get(i) - keyValues.get(i)) <= VALUE_TOLERANCE).length;
  return { accurate: ok, found: valued.length, rate: ratio(ok, valued.length) };
}

function fpKind(i, universe, keyPairMembers) {
  if (i.startsWith("PAIR:")) {
    const members = i.slice(5).split("+");
    if (universe.size && !members.every((m) => universe.has(m))) return "nonexistent_id";
    return members.some((m) => keyPairMembers.has(m)) ? "half_pair" : "wrong_pair";
  }
  return universe.has(i) ? "real_line" : "nonexistent_id";
}

function score(finalItems, keyValues, universe, keyItems = []) {
  const finalIds = [...new Set(ids(finalItems))];
  const values = new Map();
  for (const it of finalItems) {
    const id = norm(it.id);
    if (!values.has(id)) values.set(id, it.value === undefined ? null : it.value);
  }
  const tp = finalIds.filter((i) => keyValues.has(i));
  const fps = finalIds.filter((i) => !keyValues.has(i));
  const pairMembers = new Set();
  for (const k of keyItems) if (k.type === "pair") for (const n of (k.needs || [])) pairMembers.add(norm(n));
  const found = new Set(tp);
  const byType = new Map();
  for (const k of keyItems) {
    const label = itemLabel(k);
    const [f, n] = byType.get(label) || [0, 0];
    byType.set(label, [f + (found.has(norm(k.id)) ? 1 : 0), n + 1]);
  }
  const by_type = {};
  for (const [t, [f, n]] of byType) by_type[t] = { found: f, total: n };
  return {
    recall: ratio(tp.length, keyValues.size),
    precision: ratio(tp.length, finalIds.length),
    true_positives: tp.length,
    final_count: finalIds.length,
    duplicates_in_final: finalItems.length - finalIds.length,
    false_positives: fps.map((i) => ({ id: i, kind: fpKind(i, universe, pairMembers) })),
    value_accuracy: valueAccuracy(tp, values, keyValues),
    by_type,
  };
}

function keyValuesOf(run) {
  const m = new Map();
  for (const k of run.items.key) m.set(norm(k.id), k.value === undefined ? null : k.value);
  return m;
}

export function swarmAutopsy(run) {
  const keyValues = keyValuesOf(run);
  const universe = new Set((run.items.universe || []).map(norm));
  const sw = run.swarm;
  const workers = sw.workers;
  const slices = workers.map((w) => new Set(w.slice.map(norm)));
  const reported = workers.map((w) => new Set(ids(w.reported)));
  const finalItems = sw.merger.final;
  const finalIds = new Set(ids(finalItems));
  const reached = workers.map((w) => reachedIds(w.slice, w.call, w.status));

  const perItem = [];
  for (const k of run.items.key) {
    const item = norm(k.id);
    const needs = (nonEmpty(k.needs) ? k.needs : [item]).map(norm);
    const b = bucketOf(item, slices, reported, finalIds, reached, needs, k.context);
    perItem.push({
      id: item, type: itemLabel(k), bucket: b, needs,
      in_slices: workers.filter((w, i) => needs.some((n) => slices[i].has(n))).map((w) => w.worker),
      complete_in: workers.filter((w, i) => needs.every((n) => slices[i].has(n))).map((w) => w.worker),
      reported_by: workers.filter((w, i) => reported[i].has(item)).map((w) => w.worker),
    });
  }
  const counts = {};
  for (const p of perItem) counts[p.bucket] = (counts[p.bucket] || 0) + 1;

  const sliceCount = new Map();
  for (const sl of slices) for (const i of sl) sliceCount.set(i, (sliceCount.get(i) || 0) + 1);
  const allIds = universe.size ? universe : new Set(sliceCount.keys());
  const sc = score(finalItems, keyValues, universe, run.items.key);
  const anyReported = new Set();
  for (const r of reported) for (const i of r) anyReported.add(i);
  const fpKept = [], fpMerger = [];
  for (const fp of sc.false_positives) (anyReported.has(fp.id) ? fpKept : fpMerger).push(fp);
  const workerFps = [...anyReported].filter((i) => !keyValues.has(i));

  const notes = [];
  for (const p of perItem) {
    if (p.bucket === "kept" && !p.reported_by.length) notes.push(`${p.id} kept although no worker reported it (merger guess)`);
    const stray = p.reported_by.filter((w) => !p.in_slices.includes(w));
    if (stray.length) notes.push(`${p.id} reported by worker(s) ${pyList(stray)} that were not given it`);
  }
  const flags = [];
  if (sw.planner.status !== "ok") flags.push(`planner ${pyStr(sw.planner.status)}: no usable split`);
  for (const w of workers) if (w.status !== "ok") flags.push(`worker ${w.worker} ${pyStr(w.status)}`);
  if (sw.merger.status !== "ok" && sw.merger.status !== null && sw.merger.status !== undefined) {
    flags.push(`merger ${sw.merger.status}`);
  }

  const buckets = {};
  for (const b of BUCKETS) buckets[b] = counts[b] || 0;
  return {
    key_count: keyValues.size,
    buckets,
    lost: LOSS_BUCKETS.reduce((a, b) => a + (counts[b] || 0), 0),
    per_item: perItem,
    coverage: {
      lines: allIds.size,
      lines_unassigned: [...allIds].filter((i) => !sliceCount.get(i)).length,
      lines_in_2plus_slices: [...sliceCount.values()].filter((c) => c >= 2).length,
      key_lines_in_2plus_slices: [...keyValues.keys()].filter((i) => (sliceCount.get(i) || 0) >= 2).length,
    },
    false_positives: {
      worker_reported_kept: fpKept, invented_by_merger: fpMerger,
      worker_fps_filtered_by_merger: workerFps.filter((i) => !finalIds.has(i)).length,
    },
    score: sc,
    flags,
    notes,
  };
}

export function baselineAutopsy(run) {
  const b = run.baseline;
  if (!b) return { status: "absent" };
  if (b.final === null || b.final === undefined) {
    const call = b.call || {};
    return { status: b.status ?? null, requested_tokens: call.requested_tokens ?? null,
      limit_tokens: call.limit_tokens ?? null, limit_kind: call.limit_kind ?? null };
  }
  const keyValues = keyValuesOf(run);
  const universe = new Set((run.items.universe || []).map(norm));
  const sc = score(b.final, keyValues, universe, run.items.key);
  const found = new Set(ids(b.final));
  const reached = reachedIds(run.items.universe || [], b.call, b.status);
  const needs = new Map();
  for (const k of run.items.key) needs.set(norm(k.id), (nonEmpty(k.needs) ? k.needs : [k.id]).map(norm));
  const missed = [...keyValues.keys()].filter((i) => !found.has(i));
  const unreached = reached === null ? [] : missed.filter((i) => !needs.get(i).every((n) => reached.has(n)));
  return { status: b.status ?? null, score: sc, missed: missed.length, missed_unreached: unreached.length };
}

export function crossCheck(s, b, run) {
  const missed = s.per_item.filter((p) => MISSED_BUCKETS.includes(p.bucket)).map((p) => p.id);
  if (!("score" in b)) return { assigned_missed: missed.length, baseline_also_missed: null, ids: null };
  const baseIds = new Set(ids(run.baseline.final));
  const also = missed.filter((i) => !baseIds.has(i));
  return { assigned_missed: missed.length, baseline_also_missed: also.length, ids: also };
}

export function autopsy(run) {
  const s = swarmAutopsy(run), b = baselineAutopsy(run);
  return { run_id: run.run_id ?? null, swarm: s, baseline: b, cross: crossCheck(s, b, run) };
}

// ---------- site helpers (not in autopsy.py; used for labels only) ----------

/** Same as Python f"{100 * x:.0f}%": halves round to even (12.5% -> "12%"), as in the CLI tables. */
export function pct(x) {
  if (x === null || x === undefined) return "n/a";
  const v = 100 * x, f = Math.floor(v), d = v - f;
  const r = Math.abs(d - 0.5) < 1e-9 ? (f % 2 === 0 ? f : f + 1) : Math.round(v);
  return `${r}%`;
}

/** Deterministic: true when some worker's slice held every row of the task (D29 note, plan §4). */
export function noSplit(run) {
  const universe = new Set((run.items.universe || []).map(norm));
  if (!universe.size) return false;
  return run.swarm.workers.some((w) => {
    const sl = new Set(w.slice.map(norm));
    return [...universe].every((i) => sl.has(i));
  });
}

/** Items kept in `rep` but not in `orig` (recovered) and the reverse (newly lost). */
export function replayDiff(orig, rep) {
  const kept = (a) => new Set(a.per_item.filter((p) => p.bucket === "kept").map((p) => p.id));
  const k0 = kept(orig), k1 = kept(rep);
  return { recovered: [...k1].filter((i) => !k0.has(i)), newly_lost: [...k0].filter((i) => !k1.has(i)) };
}
