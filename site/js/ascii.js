// ASCII stage (DESIGN.md section 2-4, SITE_RULES.md; DECISIONS D32). One sticky canvas beside the
// story; each story section names a scene. Every glyph is a real row of the run (row number and
// line id or rate code); scenes place rows where the run put them:
//   ledger-whole  the rows as one block                       (the task)
//   scatter       the block splits into the workers' real ranges   (scatter = split)
//   dim           workers that returned nothing dim            (dimming = empty-handed worker)
//   reform        the columns reform; only kept items stay lit  (reform = merge)
//   rescatter     R4's real ranges, the rate table copied to every worker
//   apart         each far pair's two rows light up, in different columns
// Rules: the canvas sits in its own column, never over text; dropped below 1000px; one still frame
// under prefers-reduced-motion; the loop runs only while something moves and the stage is visible.

const COLORS = { grey: "#9a9a9a", pink: "#e39bd2", white: "#f2f2f2", lav: "#8e6fa3" };
const FLICKER = "·:;+=*#%";
const TRANSITION_MS = 900, MAX_DELAY_MS = 320, PUSH_RADIUS = 80, PUSH_PX = 22;

function hash(n) { // deterministic 0..1 per glyph, so the scatter looks the same every visit
  let x = Math.imul(n ^ 0x9e3779b9, 0x85ebca6b); x ^= x >>> 13; x = Math.imul(x, 0xc2b2ae35); x ^= x >>> 16;
  return (x >>> 0) / 4294967296;
}
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function startAscii(stage, model, sections) {
  const canvas = stage.querySelector("canvas");
  const wide = matchMedia("(min-width: 1000px)");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const ctx = canvas.getContext("2d");
  const dotsLayer = document.createElement("div"); // parallax dot field (CSS), behind the canvas
  dotsLayer.className = "ascii-dots";
  stage.prepend(dotsLayer);
  const byId = new Map(model.rows.map((r) => [r.id, r]));

  // ---- tokens: one per row, plus copies for rows a scene shows in several columns (R4's table)
  const layouts = [model.columns, model.columnsR4].filter(Boolean);
  const copies = new Map(model.rows.map((r) => [r.id, 1]));
  for (const cols of layouts) {
    const n = new Map();
    for (const col of cols) for (const id of col) n.set(id, (n.get(id) || 0) + 1);
    for (const [id, k] of n) copies.set(id, Math.max(copies.get(id) || 1, k));
  }
  const tokens = [];
  for (const r of model.rows) for (let k = 0; k < copies.get(r.id); k++) tokens.push({ id: r.id, k, row: r });
  const glyphs = [];
  tokens.forEach((t, ti) => {
    [...t.row.text].forEach((ch, ci) => {
      const g = glyphs.length;
      glyphs.push({ t: ti, ci, ch, x: 0, y: 0, a: 0, c: "grey", sx: 0, sy: 0, sa: 0, sc: "grey",
        tx: 0, ty: 0, ta: 0, tc: "grey", dx: 0, dy: 0,
        delay: hash(g * 3 + 1) * MAX_DELAY_MS, ang: hash(g * 3 + 2) * Math.PI * 2, amp: 10 + hash(g * 3 + 3) * 26 });
    });
  });
  const maxLen = Math.max(...model.rows.map((r) => r.text.length));
  const firstGlyph = new Int32Array(tokens.length).fill(-1);
  glyphs.forEach((g, i) => { if (firstGlyph[g.t] < 0) firstGlyph[g.t] = i; });
  const loose = new Uint8Array(tokens.length); // 1 = draw this row glyph by glyph this frame
  let tokenImages = new Map();
  const dots = dotsLayer;

  // ---- geometry and glyph atlas (rebuilt on resize)
  let W = 0, H = 0, dpr = 1, fs = 10, lineH = 14, charW = 6, atlas = null, cellW = 0, cellH = 0;
  const charset = [...new Set([...model.rows.map((r) => r.text).join(""), ...FLICKER, ..."Worker 0123456789"])];
  function buildAtlas() {
    atlas = {};
    cellW = Math.ceil(charW * dpr) + 2; cellH = Math.ceil(lineH * dpr);
    for (const [name, col] of Object.entries(COLORS)) {
      const c = document.createElement("canvas");
      c.width = cellW * charset.length; c.height = cellH;
      const x = c.getContext("2d");
      x.font = `${fs * dpr}px "JetBrains Mono", ui-monospace, monospace`;
      x.textBaseline = "middle"; x.fillStyle = col;
      charset.forEach((ch, i) => x.fillText(ch, i * cellW + 1, cellH / 2));
      atlas[name] = c;
    }
  }
  const charIndex = new Map(charset.map((ch, i) => [ch, i]));

  function measure() {
    const r = stage.getBoundingClientRect();
    W = Math.max(1, r.width); H = Math.max(1, r.height);
    dpr = Math.min(2, devicePixelRatio || 1);
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    canvas.style.width = `${W}px`; canvas.style.height = `${H}px`;
    const maxRows = Math.max(Math.ceil(model.rows.length / 2), ...layouts.flat().map((c) => c.length)) + 3;
    const maxCols = Math.max(2, ...layouts.map((c) => c.length));
    const byHeight = (H - 48) / maxRows / 1.45;
    const byWidth = (W - 32) / (maxCols * (maxLen + 2.2)) / 0.6;
    fs = Math.max(7, Math.min(13, byHeight, byWidth));
    lineH = fs * 1.45; charW = fs * 0.6;
    buildAtlas();
    tokenImages = new Map();
  }

  // ---- scenes: a target (x, y, alpha, colour) for every token; spare copies hide on their row
  const colX = (n, i) => {
    const colW = (maxLen + 2.2) * charW;
    const total = n * colW;
    return (W - total) / 2 + i * colW;
  };
  function place(cols, style) {
    const targets = new Array(tokens.length).fill(null);
    const used = new Map();
    cols.forEach((col, ci) => col.forEach((id, ri) => {
      const k = used.get(id) || 0; used.set(id, k + 1);
      const ti = tokens.findIndex((t) => t.id === id && t.k === k);
      if (ti < 0) return;
      targets[ti] = { x: colX(cols.length, ci), y: 40 + ri * lineH, ...style(byId.get(id), ci) };
    }));
    tokens.forEach((t, ti) => {
      if (targets[ti]) return;
      const home = targets[tokens.findIndex((u) => u.id === t.id && targets[tokens.indexOf(u)])] ;
      targets[ti] = { ...(home || { x: W / 2, y: H / 2 }), a: 0, c: "grey" };
    });
    return targets;
  }
  const block = () => { // the rows as one block: two touching half-columns in ledger order
    const ids = model.rows.map((r) => r.id), half = Math.ceil(ids.length / 2);
    return [ids.slice(0, half), ids.slice(half)];
  };
  const base = (r, a = 0.8) => (r.rate ? { a: Math.min(1, a + 0.1), c: "lav" } : { a, c: "grey" });
  const SCENES = {
    "ledger-whole": () => ({ targets: place(block(), (r) => base(r)), labels: null, tight: true }),
    scatter: () => ({ targets: place(model.columns, (r) => base(r)), labels: model.columns }),
    dim: () => ({ targets: place(model.columns, (r, ci) => (model.emptyWorkers.includes(ci) ? { a: 0.13, c: r.rate ? "lav" : "grey" } : base(r))), labels: model.columns }),
    reform: () => ({ targets: place(block(), (r) => (model.kept.has(r.id) ? { a: 1, c: "white" } : { a: 0.2, c: r.rate ? "lav" : "grey" })), labels: null, tight: true }),
    rescatter: () => (model.columnsR4
      ? { targets: place(model.columnsR4, (r) => (model.keptR4.has(r.id) ? { a: 1, c: "white" } : base(r, 0.42))), labels: model.columnsR4 }
      : SCENES.scatter()),
    apart: () => ({ targets: place(model.columns, (r) => (model.farRows.has(r.id) ? { a: 1, c: "pink" } : { a: 0.14, c: r.rate ? "lav" : "grey" })), labels: model.columns }),
  };

  // ---- state
  let scene = "ledger-whole", current = null, t0 = 0, labelSet = null, labelFrom = 0;
  let pointer = null, lastPointer = 0, lastScroll = 0, visible = true, frame = 0, running = false;

  function applyScene(name, instant) {
    if (!SCENES[name]) return;
    scene = name;
    current = SCENES[name]();
    // tight block: pull the two half-columns together so they read as one block
    const shift = current.tight ? ((maxLen + 2.2) * charW - (maxLen + 1.4) * charW) / 2 : 0;
    for (const g of glyphs) {
      const tg = current.targets[g.t];
      const left = tg.x + (current.tight ? (tg.x < W / 2 ? shift : -shift) : 0);
      g.sx = g.x; g.sy = g.y; g.sa = g.a; g.sc = g.c;
      g.tx = left + g.ci * charW; g.ty = tg.y; g.ta = tg.a; g.tc = tg.c;
      if (instant) { g.x = g.tx; g.y = g.ty; g.a = g.ta; g.c = g.tc; }
    }
    labelSet = current.labels; labelFrom = performance.now();
    t0 = instant ? -1e9 : performance.now();
    kick();
  }

  let settledAt = -1;
  function step(now) {
    let moving = false;
    const p = reduce.matches ? null : pointer;
    const inTransition = now - t0 < MAX_DELAY_MS + TRANSITION_MS;
    loose.fill(0);
    if (!inTransition && settledAt !== t0) { // snap everything to its target once, then skip the maths
      for (const g of glyphs) { g.x = g.tx; g.y = g.ty; g.a = g.ta; g.c = g.tc; g.flick = false; }
      settledAt = t0;
    }
    for (const g of glyphs) {
      if (inTransition) {
        const t = Math.min(1, Math.max(0, (now - t0 - g.delay) / TRANSITION_MS));
        const e = ease(t), arc = Math.sin(Math.PI * t) * g.amp; // scatter outward, then settle
        g.x = g.sx + (g.tx - g.sx) * e + Math.cos(g.ang) * arc;
        g.y = g.sy + (g.ty - g.sy) * e + Math.sin(g.ang) * arc;
        g.a = g.sa + (g.ta - g.sa) * e;
        g.c = t < 0.5 ? g.sc : g.tc;
        g.flick = !lite && t > 0.12 && t < 0.82 && hash(g.t * 131 + g.ci * 7 + Math.floor(now / 70)) < 0.35;
        if (t < 1) { moving = true; if (!lite) loose[g.t] = 1; } // lite: the row moves as one image
      }
      // pointer: nearby glyphs drift away, then re-form after it passes
      let wx = 0, wy = 0;
      if (p) {
        const ddx = g.x - p.x, ddy = g.y - p.y;
        if (ddx < PUSH_RADIUS && ddx > -PUSH_RADIUS && ddy < PUSH_RADIUS && ddy > -PUSH_RADIUS) {
          const d = Math.sqrt(ddx * ddx + ddy * ddy);
          if (d < PUSH_RADIUS && d > 0.01) { const f = (1 - d / PUSH_RADIUS) ** 2 * PUSH_PX; wx = (ddx / d) * f; wy = (ddy / d) * f; }
        }
      }
      if (wx || wy || g.dx || g.dy) {
        g.dx += (wx - g.dx) * 0.16; g.dy += (wy - g.dy) * 0.16;
        if (!wx && !wy && Math.abs(g.dx) + Math.abs(g.dy) < 0.15) { g.dx = 0; g.dy = 0; }
        else { moving = true; loose[g.t] = 1; }
      }
    }
    return moving;
  }

  function tokenImage(ti, color) { // one row pre-rendered from the glyph atlas, per colour
    const key = ti * 8 + Object.keys(COLORS).indexOf(color);
    let img = tokenImages.get(key);
    if (!img) {
      const text = tokens[ti].row.text;
      img = document.createElement("canvas");
      img.width = Math.ceil((text.length + 1) * charW * dpr) + cellW; img.height = cellH;
      const x = img.getContext("2d");
      [...text].forEach((ch, i) => {
        const k = charIndex.get(ch);
        if (k !== undefined) x.drawImage(atlas[color], k * cellW, 0, cellW, cellH, Math.round(i * charW * dpr), 0, cellW, cellH);
      });
      tokenImages.set(key, img);
    }
    return img;
  }

  function draw(now) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    // depth: a faint dot field drifting slower than the page (parallax), still under reduced motion
    // depth: the dot field is a separate CSS layer behind the canvas, moved by the compositor
    if (dots) dots.style.transform = `translate3d(0, ${-(reduce.matches ? 0 : (scrollY * 0.12) % 26)}px, 0)`;
    // column labels (decorative; the page text says the same)
    if (labelSet) {
      const la = Math.min(1, (now - labelFrom) / 600) * 0.75;
      ctx.globalAlpha = reduce.matches ? 0.75 : la;
      ctx.fillStyle = COLORS.pink;
      ctx.font = `${Math.max(9, fs * 0.9)}px "Inter", system-ui, sans-serif`;
      labelSet.forEach((col, i) => ctx.fillText(`worker ${i + 1}`, colX(labelSet.length, i), 22));
    }
    for (let ti = 0; ti < tokens.length; ti++) {
      const g0 = glyphs[firstGlyph[ti]];
      if (!loose[ti]) { // settled row: one draw
        if (g0.a < 0.01) continue;
        const img = tokenImage(ti, g0.c);
        ctx.globalAlpha = g0.a;
        ctx.drawImage(img, g0.x, g0.y - lineH / 2, img.width / dpr, img.height / dpr);
        continue;
      }
      for (let gi = firstGlyph[ti]; gi < glyphs.length && glyphs[gi].t === ti; gi++) {
        const g = glyphs[gi];
        if (g.a < 0.01) continue;
        const ch = g.flick && !reduce.matches ? FLICKER[(g.ci + g.t) % FLICKER.length] : g.ch;
        const i = charIndex.get(ch);
        if (i === undefined) continue;
        ctx.globalAlpha = g.a;
        ctx.drawImage(atlas[g.c], i * cellW, 0, cellW, cellH, g.x + g.dx, g.y + g.dy - lineH / 2, cellW / dpr, cellH / dpr);
      }
    }
    ctx.globalAlpha = 1;
  }

  const stats = { frames: 0, ms: 0, max: 0 };
  // lite mode for slow machines: if animation frames run long (median over 24ms across 40 frames),
  // rows move as whole rows during transitions (no per-letter scatter or flicker). Same scenes.
  let lite = false, lastFrame = 0;
  const gaps = [];
  function loop(now) {
    frame = 0;
    if (lastFrame && !lite) {
      gaps.push(now - lastFrame);
      if (gaps.length > 40) gaps.shift();
      if (gaps.length === 40 && [...gaps].sort((x, y) => x - y)[20] > 24) lite = true;
    }
    lastFrame = now;
    const c0 = performance.now();
    const moving = step(now);
    draw(now);
    const c = performance.now() - c0;
    stats.frames++; stats.ms += c; stats.max = Math.max(stats.max, c);
    const recent = now - lastPointer < 1200 || now - lastScroll < 250;
    if (visible && !document.hidden && (moving || recent) && !reduce.matches) frame = requestAnimationFrame(loop);
    else { running = false; lastFrame = 0; }
  }
  function kick() {
    if (!wide.matches) return;
    if (reduce.matches) { step(performance.now()); draw(performance.now()); return; }
    if (!running && visible && !document.hidden) { running = true; frame = requestAnimationFrame(loop); }
  }

  // ---- wiring
  function init() {
    if (!wide.matches) return false;
    measure();
    applyScene(scene, true);
    return true;
  }
  let ready = false;
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) applyScene(e.target.dataset.scene, reduce.matches);
  }, { rootMargin: "-40% 0px -55% 0px" });
  sections.forEach((s) => s.dataset.scene && io.observe(s));
  new IntersectionObserver((es) => { visible = es[0].isIntersecting; if (visible) kick(); }).observe(stage);
  new ResizeObserver(() => { if (!wide.matches) return; ready = true; measure(); applyScene(scene, true); }).observe(stage);
  stage.addEventListener("pointermove", (e) => {
    if (reduce.matches) return;
    const r = canvas.getBoundingClientRect();
    pointer = { x: e.clientX - r.left, y: e.clientY - r.top }; lastPointer = performance.now(); kick();
  }, { passive: true });
  stage.addEventListener("pointerleave", () => { pointer = null; lastPointer = performance.now(); kick(); }, { passive: true });
  addEventListener("scroll", () => { lastScroll = performance.now(); kick(); }, { passive: true });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) kick(); });
  reduce.addEventListener("change", () => applyScene(scene, true));
  wide.addEventListener("change", () => { if (wide.matches) init(); });
  (document.fonts ? document.fonts.load('12px "JetBrains Mono"') : Promise.resolve()).then(() => { ready = init() || ready; });

  window.__ascii = { glyphs: glyphs.length, scene: () => scene, // for the performance check
    stats: () => ({ frames: stats.frames, avg_ms: +(stats.ms / Math.max(1, stats.frames)).toFixed(2), max_ms: +stats.max.toFixed(2), lite }) };
}
