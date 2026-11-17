// Loads every page at several widths, scrolls the landing page top to bottom, and fails on any page
// error, console error or failed request (D36). Also resizes the landing page 1440 -> 800 -> 1440
// to exercise the ASCII engine's pause/resume, and reports whether the engine is running.
//   node tools/check_errors.mjs [base url, default http://127.0.0.1:8765/]
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = (process.argv[2] || "http://127.0.0.1:8765/").replace(/\/?$/, "/");
const PAGES = ["index.html", "explorer.html", "try.html"];
const WIDTHS = [360, 800, 999, 1000, 1440];
const port = 9336;
const chrome = spawn(process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe",
  ["--headless=new", "--disable-gpu", `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "ce-"))}`, "about:blank"],
  { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl;
for (let i = 0; i < 50 && !wsUrl; i++) {
  try { wsUrl = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page").webSocketDebuggerUrl; }
  catch { await sleep(200); }
}
const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const pend = new Map();
let problems = [];
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); return; }
  if (m.method === "Runtime.exceptionThrown") {
    const d = m.params.exceptionDetails;
    problems.push(`page error: ${(d.exception && d.exception.description) || d.text}`.split("\n").slice(0, 2).join(" | "));
  }
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
    problems.push("console.error: " + m.params.args.map((a) => a.value ?? a.description).join(" "));
  }
  if (m.method === "Log.entryAdded" && m.params.entry.level === "error") {
    problems.push(`log error: ${m.params.entry.text} ${m.params.entry.url || ""}`.trim());
  }
  if (m.method === "Network.loadingFailed" && !m.params.canceled) problems.push(`request failed: ${m.params.errorText}`);
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true })).result.result?.value;
await send("Runtime.enable"); await send("Log.enable"); await send("Network.enable");

const setWidth = (w) => send("Emulation.setDeviceMetricsOverride", { width: w, height: w <= 700 ? 780 : 900, deviceScaleFactor: 1, mobile: w <= 700 });
async function scrollThrough() {
  const h = await evaluate("document.documentElement.scrollHeight");
  for (let y = 0; y <= h; y += 400) { await evaluate(`scrollTo(0, ${y})`); await sleep(120); }
  await sleep(600);
}
const engine = () => evaluate("window.__ascii ? (window.__ascii.active ? window.__ascii.active() : 'built') : 'not built'");

let failed = 0;
const report = (label, extra = "") => {
  const ok = problems.length === 0;
  if (!ok) failed++;
  console.log(`${ok ? "OK  " : "FAIL"} ${label}${extra}${ok ? "" : "\n      " + problems.join("\n      ")}`);
  problems = [];
};

for (const w of WIDTHS) {
  for (const page of PAGES) {
    await setWidth(w);
    problems = [];
    await send("Page.navigate", { url: BASE + page });
    await sleep(3000);
    if (page === "index.html") await scrollThrough();
    else await sleep(800);
    report(`${String(w).padStart(4)}px ${page}`, page === "index.html" ? `  (ASCII engine: ${await engine()})` : "");
  }
}

// resize: wide -> narrow -> wide on the landing page (pause and resume the engine)
problems = [];
await setWidth(1440);
await send("Page.navigate", { url: BASE + "index.html" });
await sleep(3000);
await evaluate("document.querySelector('#split') && document.querySelector('#split').scrollIntoView()");
await sleep(1500);
const states = [`1440: ${await engine()}`];
await setWidth(800); await sleep(800); await scrollThrough(); states.push(`800: ${await engine()}`);
await setWidth(1440); await sleep(800); await scrollThrough(); states.push(`1440: ${await engine()}`);
report("resize 1440 -> 800 -> 1440 index.html", `  (ASCII engine active: ${states.join(", ")})`);

ws.close();
chrome.kill();
console.log(failed ? `${failed} check(s) failed` : "all checks passed: zero errors");
process.exit(failed ? 1 : 0);
