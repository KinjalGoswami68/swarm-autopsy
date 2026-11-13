// Shared DOM helpers. Data from run files is only ever inserted as text (never innerHTML):
// briefs and replies are model output.
export const REPO_URL = "https://github.com/KinjalGoswami68/swarm-autopsy";

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

/** A table: head = [labels], rows = [[cells]]; a cell is text or a Node. */
export function table(head, rows, opts = {}) {
  return el("div", { class: "table-wrap" },
    el("table", { class: opts.class || "" },
      opts.caption ? el("caption", { text: opts.caption }) : null,
      el("thead", {}, el("tr", {}, head.map((h) => el("th", { scope: "col", text: h })))),
      el("tbody", {}, rows.map((r) => el("tr", { class: r.className || "" },
        (r.cells || r).map((c, i) => el(i === 0 ? "th" : "td", i === 0 ? { scope: "row" } : {}, c)))))));
}

/** The fixed family-2 sentence, read from the run file (task.fixed_sentence); null if absent. */
export function caveat(run) {
  const s = run && run.task && run.task.fixed_sentence;
  return s ? el("p", { class: "caveat", role: "note" }, s) : null;
}

export function footer() {
  return el("footer", { class: "site-footer" },
    el("p", {}, "Built by Kinjal Goswami · ", el("a", { href: REPO_URL, text: "source on GitHub" })),
    el("p", {}, "An independent project, not affiliated with or endorsed by Acyclic Labs."));
}

export function nav(current) {
  const link = (href, label) => el("a", { href, "aria-current": current === href ? "page" : null, text: label });
  return el("nav", { class: "site-nav", "aria-label": "Site" },
    link("index.html", "Story"), link("explorer.html", "Run explorer"), link("try.html", "Try your own run"));
}

export function frac(n, d) {
  return `${n}/${d}`;
}
