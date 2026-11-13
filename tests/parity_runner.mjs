// Node runner for the site parity test: prints {path: autopsy(run)} for each file argument,
// plus pct() of the numbers in PCT_CASES when that variable is set.
import { readFileSync } from "node:fs";
import { autopsy, pct } from "../site/js/autopsy.js";

const out = {};
for (const path of process.argv.slice(2)) out[path] = autopsy(JSON.parse(readFileSync(path, "utf8")));
if (process.env.PCT_CASES) out.__pct__ = JSON.parse(process.env.PCT_CASES).map(pct);
process.stdout.write(JSON.stringify(out));
