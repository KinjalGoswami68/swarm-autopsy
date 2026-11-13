// Minimal JSON Schema checker for schema/run.schema.json (DECISIONS D30). It implements exactly the
// keywords that schema uses and refuses to load a schema with any other keyword, so it can never
// silently skip a rule. tests/test_site_validate.py checks it agrees with Python's jsonschema.
const SUPPORTED = new Set(["$schema", "$id", "title", "description", "$defs", "$ref", "type",
  "required", "properties", "items", "enum", "const", "minLength", "minimum", "minItems",
  "maxItems", "oneOf"]);

export function checkSupported(schema, path = "#") {
  if (Array.isArray(schema)) { schema.forEach((s, i) => checkSupported(s, `${path}/${i}`)); return; }
  if (!schema || typeof schema !== "object") return;
  for (const k of Object.keys(schema)) {
    if (!SUPPORTED.has(k)) throw new Error(`schema keyword not supported by validate.js: ${k} at ${path}`);
  }
  for (const k of ["$defs", "properties"]) {
    if (schema[k]) for (const [n, s] of Object.entries(schema[k])) checkSupported(s, `${path}/${k}/${n}`);
  }
  if (schema.items) checkSupported(schema.items, `${path}/items`);
  if (schema.oneOf) checkSupported(schema.oneOf, `${path}/oneOf`);
}

function typeOf(v) {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  if (typeof v === "number") return Number.isInteger(v) ? "integer" : "number";
  return typeof v; // string, boolean, object
}

function typeMatches(v, t) {
  const actual = typeOf(v);
  return actual === t || (t === "number" && actual === "integer");
}

function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

function walk(root, schema, v, path, errors) {
  if (schema.$ref) {
    const name = schema.$ref.replace(/^#\/\$defs\//, "");
    return walk(root, root.$defs[name], v, path, errors);
  }
  const here = path || "(root)";
  if (schema.type !== undefined) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((t) => typeMatches(v, t))) {
      errors.push({ path: here, message: `expected ${types.join(" or ")}, got ${typeOf(v)}` });
      return;
    }
  }
  if (schema.const !== undefined && !equal(v, schema.const)) errors.push({ path: here, message: `must be ${JSON.stringify(schema.const)}` });
  if (schema.enum && !schema.enum.some((e) => equal(e, v))) errors.push({ path: here, message: `must be one of ${schema.enum.map((e) => JSON.stringify(e)).join(", ")}` });
  if (typeof v === "string" && schema.minLength !== undefined && v.length < schema.minLength) errors.push({ path: here, message: `shorter than ${schema.minLength}` });
  if (typeof v === "number" && schema.minimum !== undefined && v < schema.minimum) errors.push({ path: here, message: `less than ${schema.minimum}` });
  if (Array.isArray(v)) {
    if (schema.minItems !== undefined && v.length < schema.minItems) errors.push({ path: here, message: `fewer than ${schema.minItems} items` });
    if (schema.maxItems !== undefined && v.length > schema.maxItems) errors.push({ path: here, message: `more than ${schema.maxItems} items` });
    if (schema.items) v.forEach((x, i) => walk(root, schema.items, x, `${path}/${i}`, errors));
  }
  if (v && typeof v === "object" && !Array.isArray(v)) {
    for (const r of schema.required || []) if (!(r in v)) errors.push({ path: here, message: `missing required field "${r}"` });
    for (const [k, s] of Object.entries(schema.properties || {})) if (k in v) walk(root, s, v[k], path ? `${path}/${k}` : k, errors);
  }
  if (schema.oneOf) {
    const passing = schema.oneOf.filter((s) => { const e = []; walk(root, s, v, path, e); return !e.length; }).length;
    if (passing !== 1) errors.push({ path: here, message: `must match exactly one of ${schema.oneOf.length} forms (matched ${passing})` });
  }
}

/** Returns a list of {path, message}; empty means valid. */
export function validate(schema, data) {
  checkSupported(schema);
  const errors = [];
  walk(schema, schema, data, "", errors);
  return errors;
}
