// "Try your own run": read a run file locally (nothing is uploaded), validate it against
// schema/run.schema.json with validate.js, then render it with the explorer's run view.
import { validate } from "./validate.js";
import { renderRun } from "./runview.js";
import { el, nav, footer } from "./ui.js";

let schemaPromise = null;
const loadSchema = () => (schemaPromise ||= fetch("schema/run.schema.json").then((r) => r.json()));

async function handle(file) {
  const status = document.getElementById("try-status");
  const view = document.getElementById("run-view");
  view.replaceChildren();
  status.replaceChildren(el("p", {}, `Reading ${file.name} (${Math.round(file.size / 1024)} KB) in your browser…`));
  let run;
  try {
    run = JSON.parse(await file.text());
  } catch (e) {
    status.replaceChildren(el("p", { class: "error", role: "alert" }, `Not valid JSON: ${e.message}`));
    return;
  }
  const errors = validate(await loadSchema(), run);
  if (errors.length) {
    status.replaceChildren(...[
      el("p", { class: "error", role: "alert" }, `${file.name} is not a valid run file (${errors.length} problem${errors.length > 1 ? "s" : ""}). See SCHEMA.md for the format.`),
      el("ul", { class: "errors" }, errors.slice(0, 50).map((e) => el("li", {}, el("code", {}, e.path), ` ${e.message}`))),
      errors.length > 50 ? el("p", { class: "muted" }, `…and ${errors.length - 50} more.`) : null,
    ].filter(Boolean));
    return;
  }
  status.replaceChildren(el("p", { class: "ok" }, `${file.name} is a valid run file (schema version ${run.schema_version}). The breakdown below is computed in your browser.`));
  try {
    renderRun(view, run, []);
  } catch (e) {
    status.append(el("p", { class: "error", role: "alert" }, `The file passed the schema but could not be autopsied: ${e.message}`));
  }
}

function main() {
  document.body.prepend(nav("try.html"));
  document.body.append(footer());
  const input = document.getElementById("file");
  const zone = document.getElementById("drop");
  input.addEventListener("change", () => input.files[0] && handle(input.files[0]));
  for (const ev of ["dragenter", "dragover"]) zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("over"); });
  for (const ev of ["dragleave", "drop"]) zone.addEventListener(ev, () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) handle(f);
  });
}

main();
