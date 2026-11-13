// Run explorer page: pick a run (or open explorer.html?run=<run_id>), render it with runview.js.
import { loadAll, replaysByOriginal, runLabel } from "./data.js";
import { renderRun } from "./runview.js";
import { el, nav, footer } from "./ui.js";

async function main() {
  document.body.prepend(nav("explorer.html"));
  document.body.append(footer());
  const view = document.getElementById("run-view");
  const status = document.getElementById("status");
  let data;
  try {
    data = await loadAll();
  } catch (e) {
    status.textContent = `Could not load run files: ${e.message}`;
    return;
  }
  status.textContent = "";
  const reps = replaysByOriginal(data.replays);
  const groups = new Map();
  for (const r of data.runs) {
    const fam = r.run.task.family === "ledger-ctx" ? "Family 2: context and pairs" : "Family 1: independent lines";
    const key = `${fam} · ${r.run.config.model}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  const sortKey = (r) => [r.run.task.size, r.run.config.workers, r.run.task.seed];
  const picker = document.getElementById("run-picker");
  for (const [g, list] of groups) {
    list.sort((x, y) => { const a = sortKey(x), b = sortKey(y); return a[0].localeCompare(b[0]) || a[1] - b[1] || a[2] - b[2]; });
    picker.append(el("optgroup", { label: g }, list.map((r) => el("option", { value: r.run.run_id }, runLabel(r.run)
      + (reps.has(r.run.run_id) ? ` · ${reps.get(r.run.run_id).length} replays` : "")))));
  }
  const byId = new Map(data.runs.map((r) => [r.run.run_id, r.run]));
  const show = (id) => {
    const run = byId.get(id);
    if (!run) return;
    picker.value = id;
    renderRun(view, run, (reps.get(id) || []).map((r) => r.run));
    const u = new URL(location.href);
    u.searchParams.set("run", id);
    history.replaceState(null, "", u);
  };
  picker.addEventListener("change", () => show(picker.value));
  const wanted = new URL(location.href).searchParams.get("run");
  show(byId.has(wanted) ? wanted : picker.value);
}

main();
