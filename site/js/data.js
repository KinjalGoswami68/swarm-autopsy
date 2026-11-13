// Loads run files for the site. manifest.json (written by build_site.py) lists paths only.
const cache = new Map();
let manifestPromise = null;

export function loadManifest() {
  if (!manifestPromise) {
    manifestPromise = fetch("manifest.json").then((r) => {
      if (!r.ok) throw new Error(`manifest.json: HTTP ${r.status}`);
      return r.json();
    });
  }
  return manifestPromise;
}

export function loadRun(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(path);
}

/** Fetch paths with at most `limit` requests in flight (kind to small servers and slow phones). */
async function loadMany(paths, limit = 4) {
  const out = new Array(paths.length);
  let next = 0;
  const worker = async () => {
    while (next < paths.length) {
      const i = next++;
      out[i] = { path: paths[i], run: await loadRun(paths[i]) };
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, paths.length) }, worker));
  return out;
}

export async function loadAll() {
  const m = await loadManifest();
  return { runs: await loadMany(m.runs), replays: await loadMany(m.replays) };
}

/** Replays grouped by the run_id they replay, sorted by label (R1..R4). */
export function replaysByOriginal(replays) {
  const by = new Map();
  for (const r of replays) {
    const of = r.run.replay.of;
    if (!by.has(of)) by.set(of, []);
    by.get(of).push(r);
  }
  for (const list of by.values()) list.sort((a, b) => a.run.replay.label.localeCompare(b.run.replay.label));
  return by;
}

export function runLabel(run) {
  const t = run.task, c = run.config;
  const fam = t.family === "ledger-ctx" ? "family 2 (context and pairs)" : "family 1 (independent lines)";
  return `${fam} · ${c.model} · size ${t.size} · W=${c.workers} · seed ${t.seed}`;
}
