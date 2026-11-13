// Checks SITE_RULES "works at 360px with no horizontal scroll": emulates a phone (or WIDTH=1440 for
// desktop) in Chrome through the DevTools protocol, loads each URL, reports page width vs viewport,
// and saves a full-page screenshot captured beyond a normal-height viewport (so vh units are real).
//   [WIDTH=1440] node tools/check_mobile.mjs <outdir> <url> [url...]
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const [outDir, ...urls] = process.argv.slice(2);
const port = 9333;
const WIDTH = Number(process.env.WIDTH || 360), HEIGHT = WIDTH > 700 ? 900 : 780, MOBILE = WIDTH <= 700;
const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${port}`,
  `--user-data-dir=${mkdtempSync(join(tmpdir(), "cm-"))}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(200);
  }
  throw new Error("chrome did not start");
}

const ws = new WebSocket(await target());
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const pending = new Map();
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });

await send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: MOBILE });
let failed = 0;
for (const [n, url] of urls.entries()) {
  await send("Page.navigate", { url });
  await sleep(4000);
  const r = await send("Runtime.evaluate", { returnByValue: true, expression:
    "({w: document.documentElement.scrollWidth, vw: innerWidth, h: document.documentElement.scrollHeight," +
    " wide: [...document.querySelectorAll('body *')].filter(e => { const b = e.getBoundingClientRect();" +
    " return b.right > innerWidth + 1 && !e.closest('.table-wrap'); }).slice(0, 5)" +
    ".map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right))})" });
  const v = r.result.result.value;
  const ok = v.w <= v.vw;
  if (!ok) failed++;
  console.log(`${ok ? "OK  " : "FAIL"} ${url}: page width ${v.w}px, viewport ${v.vw}px${v.wide.length ? "; too wide: " + v.wide.join(", ") : ""}`);
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true,
    clip: { x: 0, y: 0, width: WIDTH, height: Math.min(v.h, 9000), scale: 1 } });
  writeFileSync(join(outDir, `${MOBILE ? "mobile" : "desktop"}_${n}.png`), Buffer.from(shot.result.data, "base64"));
}
ws.close();
chrome.kill();
process.exit(failed ? 1 : 0);
