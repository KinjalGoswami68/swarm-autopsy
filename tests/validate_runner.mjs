// Node runner for tests/test_site_validate.py: validates each JSON file against the run schema.
import { readFileSync } from "node:fs";
import { validate } from "../site/js/validate.js";

const schema = JSON.parse(readFileSync(new URL("../schema/run.schema.json", import.meta.url), "utf8"));
const out = {};
for (const p of process.argv.slice(2)) out[p] = validate(schema, JSON.parse(readFileSync(p, "utf8")));
process.stdout.write(JSON.stringify(out));
