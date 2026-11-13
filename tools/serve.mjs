// Local preview server for _site/ (127.0.0.1 only). Python's http.server reset connections
// mid-file on this Windows machine, so this one reads each file whole and sends it in one write.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, normalize, extname, resolve } from "node:path";

const root = resolve(process.argv[2] || "_site");
const port = Number(process.argv[3] || 8765);
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json", ".png": "image/png",
  ".woff2": "font/woff2", ".svg": "image/svg+xml" };

createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  let path = normalize(join(root, decodeURIComponent(url.pathname)));
  if (!path.startsWith(root)) { res.writeHead(403).end(); return; }
  if (url.pathname.endsWith("/")) path = join(path, "index.html");
  try {
    const body = await readFile(path);
    res.writeHead(200, { "Content-Type": TYPES[extname(path)] || "application/octet-stream",
      "Content-Length": body.length, "Cache-Control": "no-store" });
    res.end(body);
  } catch {
    res.writeHead(404, { "Content-Type": "text/plain" }).end("not found");
  }
}).listen(port, "127.0.0.1", () => console.log(`serving ${root} on http://127.0.0.1:${port}/`));
