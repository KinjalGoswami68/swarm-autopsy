// Viewport screenshots and checks through Chrome's DevTools protocol.
//   node tools/shoot.mjs <out.png> <url> [--width 1440] [--height 900] [--reduced]
//        [--scroll "#split"] [--wait 2500] [--pointer x,y] [--fps 3000] [--throttle 4]
// Prints page exceptions, console errors and window.__ascii; --fps measures frame times while the
// pointer sweeps across the ASCII stage and the page scrolls (SITE_RULES: 60fps).
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const args = process.argv.slice(2);
const out = args[0], url = args[1];
const opt = (name, dflt) => { const i = args.indexOf(name); return i < 0 ? dflt : args[i + 1]; };
const flag = (name) => args.includes(name);
const width = Number(opt("--width", 1440)), height = Number(opt("--height", 900));
const port = 9335;
const chrome = spawn(process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe",
  ["--headless=new", ...(flag("--gpu") ? [] : ["--disable-gpu"]), `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "sh-"))}`, "about:blank"],
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
const pend = new Map(), problems = [];
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
  if (m.method === "Runtime.exceptionThrown") problems.push("exception: " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") problems.push("console.error: " + m.params.args.map((a) => a.value ?? a.description).join(" "));
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.result?.value;

await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width <= 700 });
const throttle = Number(opt("--throttle", 1));
if (throttle > 1) await send("Emulation.setCPUThrottlingRate", { rate: throttle }); // e.g. 4 = a slower laptop CPU
if (flag("--reduced")) await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
await send("Page.navigate", { url });
await sleep(3500);
const target = opt("--scroll", null);
if (target) {
  await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(target)}); if (el) scrollTo(0, el.getBoundingClientRect().top + scrollY - innerHeight * 0.3); })()`);
}
await sleep(Number(opt("--wait", 2500)));
const pointer = opt("--pointer", null);
if (pointer) {
  const [x, y] = pointer.split(",").map(Number);
  for (let k = 0; k <= 10; k++) { await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x - 60 + k * 12, y }); await sleep(30); }
  await sleep(120);
}
const fpsMs = Number(opt("--fps", 0));
if (fpsMs) {
  await evaluate(`window.__frames = []; (function f(t){ window.__frames.push(t); if (window.__frames.length < 100000) requestAnimationFrame(f); })(performance.now()); 0`);
  const rect = await evaluate(`(() => { const r = document.querySelector('.track-stage')?.getBoundingClientRect(); return r ? [r.left, r.top, r.width, r.height] : null; })()`);
  const t0 = Date.now();
  let k = 0;
  while (Date.now() - t0 < fpsMs) {
    if (rect) await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: rect[0] + ((k * 17) % rect[2]), y: rect[1] + rect[3] / 2 + ((k * 7) % 80) - 40 });
    if (k % 6 === 0) await evaluate("scrollBy(0, 40)");
    k++;
    await sleep(16);
  }
  const ft = await evaluate(`(() => { const f = window.__frames; const d = f.slice(1).map((t, i) => t - f[i]); d.sort((a, b) => a - b);
    return { frames: d.length, median_ms: d[Math.floor(d.length / 2)].toFixed(1), p95_ms: d[Math.floor(d.length * .95)].toFixed(1), over_33ms: d.filter((x) => x > 33.4).length }; })()`);
  console.log("frame times:", JSON.stringify(ft));
  console.log("engine cost per frame:", JSON.stringify(await evaluate("window.__ascii && window.__ascii.stats ? window.__ascii.stats() : null")));
}
const state = await evaluate(`({ ascii: window.__ascii ? { glyphs: window.__ascii.glyphs, scene: window.__ascii.scene() } : null,
  stage: (() => { const s = document.querySelector('.track-stage'); if (!s) return null; const r = s.getBoundingClientRect(); return { display: getComputedStyle(s).display, top: Math.round(r.top), h: Math.round(r.height), w: Math.round(r.width) }; })(),
  reduced: matchMedia("(prefers-reduced-motion: reduce)").matches, engine: window.__ascii && window.__ascii.stats ? window.__ascii.stats() : null })`);
console.log(JSON.stringify(state));
if (problems.length) console.log("PROBLEMS:\n  " + problems.join("\n  "));
const shot = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(out, Buffer.from(shot.result.data, "base64"));
ws.close();
chrome.kill();
process.exit(problems.length ? 1 : 0);
