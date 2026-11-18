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

// light/lavLight: resting rows, brighter so they read without effort (D33); grey/lav: dimmed rows
const COLORS = { grey: "#9a9a9a", pink: "#e39bd2", white: "#f2f2f2", lav: "#8e6fa3", light: "#d6d6d6", lavLight: "#c3a6d6" };
const FLICKER = "·:;+=*#%";
const TRANSITION_MS = 900, MAX_DELAY_MS = 320, PUSH_RADIUS = 80, PUSH_PX = 22;

function hash(n) { // deterministic 0..1 per glyph, so the scatter looks the same every visit
  let x = Math.imul(n ^ 0x9e3779b9, 0x85ebca6b); x ^= x >>> 13; x = Math.imul(x, 0xc2b2ae35); x ^= x >>> 16;
  return (x >>> 0) / 4294967296;
}
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

// D36: below 1000px the canvas is not shown and the engine does no work at all: the only thing
// registered is this one media-query listener, so the engine can start if the window widens.
export function startAscii(stage, model, sections) {
  const wide = matchMedia("(min-width: 1000px)");
  let engine = null;
  const onChange = () => {
    if (wide.matches) { if (!engine) engine = boot(stage, model, sections, wide); else engine.resume(); }
    else if (engine) engine.pause();
  };
  wide.addEventListener("change", onChange);
  if (wide.matches) onChange();
}

function boot(stage, model, sections, wide) {
  const canvas = stage.querySelector("canvas");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const ctx = canvas.getContext("2d");
  const caption = stage.querySelector(".ascii-caption");
  const dotsLayer = document.createElement("div"); // parallax dot field (CSS), behind the canvas
  dotsLayer.className = "ascii-dots";
  stage.prepend(dotsLayer);
  const byId = new Map(model.rows.map((r) => [r.id, r]));

  // ---- tokens: one per row, plus copies for rows a scene shows in several columns (R4's table)
  const layouts = [model.columns, model.columnsR4, model.columnsR5].filter(Boolean);
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
  const tokenOf = new Map(tokens.map((t, i) => [`${t.id}|${t.k}`, i]));
  const maxColRows = Math.max(1, ...layouts.flat().map((c) => c.length));
  const blockCols = Math.ceil(model.rows.length / maxColRows); // the one-block view wraps to the same height
  let tokenImages = new Map();
  const dots = dotsLayer;
  let cache = null, cacheValid = false; // the settled scene, drawn once (D33)

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

  const TOP = 46; // room for the column labels
  function measure() {
    const r = canvas.getBoundingClientRect();
    W = Math.max(1, r.width); H = Math.max(1, r.height);
    dpr = Math.min(2, devicePixelRatio || 1);
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    const rowsTall = maxColRows + 1;
    const maxCols = Math.max(blockCols, ...layouts.map((c) => c.length));
    const byHeight = (H - TOP) / rowsTall / 1.3;
    const byWidth = (W - 24) / (maxCols * (maxLen + 2.2)) / 0.6;
    fs = Math.max(8, Math.min(17, byHeight, byWidth));
    charW = fs * 0.6;
    lineH = Math.min(fs * 1.6, (H - TOP) / rowsTall); // extra row spacing when the height allows
    buildAtlas();
    tokenImages = new Map();
    cache = document.createElement("canvas");
    cache.width = canvas.width; cache.height = canvas.height;
    cacheValid = false;
  }

  // ---- scenes: a target (x, y, alpha, colour) for every token; spare copies hide on their row
  const colX = (n, i, gap = 2.2) => {
    const colW = (maxLen + gap) * charW;
    const total = n * colW - gap * charW;
    return (W - total) / 2 + i * colW;
  };
  function place(cols, style, gap = 2.2) {
    const targets = new Array(tokens.length).fill(null);
    const used = new Map();
    cols.forEach((col, ci) => col.forEach((id, ri) => {
      const k = used.get(id) || 0; used.set(id, k + 1);
      const ti = tokens.findIndex((t) => t.id === id && t.k === k);
      if (ti < 0) return;
      targets[ti] = { x: colX(cols.length, ci, gap), y: TOP + ri * lineH, ...style(byId.get(id), ci) };
    }));
    tokens.forEach((t, ti) => {
      if (targets[ti]) return;
      const home = targets[tokens.findIndex((u) => u.id === t.id && targets[tokens.indexOf(u)])] ;
      targets[ti] = { ...(home || { x: W / 2, y: H / 2 }), a: 0, c: "grey" };
    });
    return targets;
  }
  const block = () => { // the rows as one block, in ledger order, wrapped to the tallest worker column
    const ids = model.rows.map((r) => r.id), per = Math.ceil(ids.length / blockCols);
    return Array.from({ length: blockCols }, (_, i) => ids.slice(i * per, (i + 1) * per));
  };
  const BLOCK_GAP = 1.2;
  const base = (r, a = 0.95) => (r.rate ? { a, c: "lavLight" } : { a, c: "light" });
  const dimmed = (r, a = 0.13) => ({ a, c: r.rate ? "lav" : "grey" });
  const SCENES = {
    "ledger-whole": () => ({ targets: place(block(), (r) => base(r), BLOCK_GAP), labels: null }),
    scatter: () => ({ targets: place(model.columns, (r) => base(r)), labels: model.columns }),
    dim: () => ({ targets: place(model.columns, (r, ci) => (model.emptyWorkers.includes(ci) ? dimmed(r) : base(r))), labels: model.columns }),
    reform: () => ({ targets: place(block(), (r) => (model.kept.has(r.id) ? { a: 1, c: "white" } : dimmed(r, 0.2)), BLOCK_GAP), labels: null }),
    rescatter: () => (model.columnsR4
      ? { targets: place(model.columnsR4, (r) => (model.keptR4.has(r.id) ? { a: 1, c: "white" } : dimmed(r, 0.38))), labels: model.columnsR4 }
      : SCENES.scatter()),
    r5: () => (model.columnsR5
      ? { targets: place(model.columnsR5, (r) => (model.keptR5.has(r.id) ? { a: 1, c: "white" } : dimmed(r, 0.38))), labels: model.columnsR5 }
      : SCENES.scatter()),
    apart: () => ({ targets: place(model.columns, (r) => (model.farRows.has(r.id) ? { a: 1, c: "pink" } : dimmed(r, 0.14))), labels: model.columns, pairs: true }),
  };

  // ---- state
  let scene = "ledger-whole", current = null, t0 = 0, labelSet = null, labelFrom = 0;
  let pointer = null, lastPointer = 0, lastScroll = 0, visible = true, frame = 0, running = false;

  function applyScene(name, instant) {
    if (!SCENES[name]) return;
    scene = name;
    if (!active || !atlas) return; // paused (narrow window): remember the scene, do nothing else
    current = SCENES[name]();
    if (caption) caption.textContent = (model.captions || {})[name] || "";
    cacheValid = false;
    prebuild();
    for (const g of glyphs) {
      const tg = current.targets[g.t];
      const left = tg.x;
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

  // build every row image the current scene needs while the browser is idle, a few at a time,
  // so scene changes do not pay for it in a frame
  let prebuildJob = 0;
  function prebuild() {
    if (!current || !active || !atlas) return;
    const want = [];
    for (let ti = 0; ti < tokens.length; ti++) {
      const tg = current.targets[ti];
      if (tg && tg.a >= 0.01) want.push([ti, tg.c]);
    }
    const job = ++prebuildJob;
    const idle = window.requestIdleCallback || ((f) => setTimeout(() => f({ timeRemaining: () => 8 }), 16));
    const work = (deadline) => {
      if (job !== prebuildJob) return;
      while (want.length && deadline.timeRemaining() > 2) { const [ti, c] = want.pop(); tokenImage(ti, c); }
      if (want.length) idle(work);
    };
    idle(work);
  }

  function rowBox(ti) { // the settled row's rectangle, with a little margin
    const g0 = glyphs[firstGlyph[ti]];
    return [g0.x - 2, g0.y - lineH / 2 - 1, (tokens[ti].row.text.length + 1) * charW + 4, lineH + 2];
  }

  function drawSettledRows(c, skipLoose) {
    for (let ti = 0; ti < tokens.length; ti++) {
      if (skipLoose && loose[ti]) continue;
      const g0 = glyphs[firstGlyph[ti]];
      if (g0.a < 0.01) continue;
      const img = tokenImage(ti, g0.c);
      c.globalAlpha = g0.a;
      c.drawImage(img, g0.x, g0.y - lineH / 2, img.width / dpr, img.height / dpr);
    }
    c.globalAlpha = 1;
  }

  function drawLabels(c, now) {
    if (!labelSet) return;
    const la = Math.min(1, (now - labelFrom) / 600) * 0.75;
    c.globalAlpha = reduce.matches ? 0.75 : la;
    c.fillStyle = COLORS.pink;
    c.font = `500 ${Math.max(10, fs * 0.85)}px "Inter", system-ui, sans-serif`;
    labelSet.forEach((col, i) => c.fillText(`worker ${i + 1}`, colX(labelSet.length, i), TOP - lineH * 0.9));
    c.globalAlpha = 1;
  }

  function drawLooseGlyphs(onlyLoose) {
    for (let ti = 0; ti < tokens.length; ti++) {
      if (onlyLoose && !loose[ti]) continue;
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

  function draw(now) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (dots) dots.style.transform = `translate3d(0, ${-(reduce.matches ? 0 : (scrollY * 0.12) % 26)}px, 0)`;
    const settled = now - t0 > MAX_DELAY_MS + TRANSITION_MS + 650; // rows, labels and pair lines at rest
    if (settled && cache) {
      if (!cacheValid) { // draw the resting scene once
        const cc = cache.getContext("2d");
        cc.setTransform(dpr, 0, 0, dpr, 0, 0);
        cc.clearRect(0, 0, W, H);
        drawSettledRows(cc, false); // resting positions; rows near the pointer are redrawn below
        drawLabels(cc, now);
        cacheValid = true;
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(cache, 0, 0);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      for (let ti = 0; ti < tokens.length; ti++) if (loose[ti]) ctx.clearRect(...rowBox(ti)); // rows near the pointer
      drawLooseGlyphs(true);
      drawPairLines(now);
      return;
    }
    drawFull(now);
  }

  function drawFull(now) {
    ctx.clearRect(0, 0, W, H);
    // column labels (decorative; the page text says the same)
    if (labelSet) {
      const la = Math.min(1, (now - labelFrom) / 600) * 0.75;
      ctx.globalAlpha = reduce.matches ? 0.75 : la;
      ctx.fillStyle = COLORS.pink;
      ctx.font = `500 ${Math.max(10, fs * 0.85)}px "Inter", system-ui, sans-serif`;
      labelSet.forEach((col, i) => ctx.fillText(`worker ${i + 1}`, colX(labelSet.length, i), TOP - lineH * 0.9));
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
    drawPairLines(now);
  }

  function drawPairLines(now) {
    if (current && current.pairs) {
      const fade = reduce.matches ? 1 : Math.min(1, Math.max(0, (now - t0 - MAX_DELAY_MS - TRANSITION_MS * 0.6) / 500));
      if (fade > 0) {
        ctx.strokeStyle = COLORS.pink; ctx.lineWidth = 1.25; ctx.globalAlpha = 0.8 * fade;
        for (const [a, b] of model.farPairs) {
          const ga = glyphs[firstGlyph[tokenOf.get(`${a}|0`)]], gb = glyphs[firstGlyph[tokenOf.get(`${b}|0`)]];
          if (!ga || !gb) continue;
          const [L, R] = ga.x <= gb.x ? [ga, gb] : [gb, ga];
          const lenL = tokens[L.t].row.text.length;
          ctx.beginPath();
          ctx.moveTo(L.x + L.dx + lenL * charW + 4, L.y + L.dy);
          ctx.lineTo(R.x + R.dx - 4, R.y + R.dy);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
    }
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
    if (!active || !wide.matches) return;
    if (reduce.matches) { step(performance.now()); draw(performance.now()); return; }
    if (!running && visible && !document.hidden) { running = true; frame = requestAnimationFrame(loop); }
  }

  // ---- wiring: attached on resume(), removed on pause() (D36)
  let active = false;
  const handlers = {
    onPointerMove: (e) => {
      if (reduce.matches) return;
      const r = canvas.getBoundingClientRect();
      pointer = { x: e.clientX - r.left, y: e.clientY - r.top }; lastPointer = performance.now(); kick();
    },
    onPointerLeave: () => { pointer = null; lastPointer = performance.now(); kick(); },
    onScroll: () => { lastScroll = performance.now(); kick(); },
    onVisibility: () => { if (!document.hidden) kick(); },
    onReduce: () => applyScene(scene, true),
  };
  let io = null, visIo = null, ro = null;
  function resume() {
    if (active || !wide.matches) return;
    active = true;
    measure();
    io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) applyScene(e.target.dataset.scene, reduce.matches);
    }, { rootMargin: "-40% 0px -55% 0px" });
    sections.forEach((s) => s.dataset.scene && io.observe(s));
    visIo = new IntersectionObserver((es) => { visible = es[0].isIntersecting; if (visible) kick(); });
    visIo.observe(stage);
    ro = new ResizeObserver(() => { if (!active) return; measure(); applyScene(scene, true); });
    ro.observe(stage);
    stage.addEventListener("pointermove", handlers.onPointerMove, { passive: true });
    stage.addEventListener("pointerleave", handlers.onPointerLeave, { passive: true });
    addEventListener("scroll", handlers.onScroll, { passive: true });
    document.addEventListener("visibilitychange", handlers.onVisibility);
    reduce.addEventListener("change", handlers.onReduce);
    applyScene(scene, true);
  }
  function pause() {
    if (!active) return;
    active = false;
    if (frame) cancelAnimationFrame(frame);
    frame = 0; running = false;
    prebuildJob++; // cancels pending idle pre-rendering
    io.disconnect(); visIo.disconnect(); ro.disconnect();
    stage.removeEventListener("pointermove", handlers.onPointerMove);
    stage.removeEventListener("pointerleave", handlers.onPointerLeave);
    removeEventListener("scroll", handlers.onScroll);
    document.removeEventListener("visibilitychange", handlers.onVisibility);
    reduce.removeEventListener("change", handlers.onReduce);
  }
  (document.fonts ? document.fonts.load('12px "JetBrains Mono"') : Promise.resolve()).then(resume);

  window.__ascii = { glyphs: glyphs.length, scene: () => scene, active: () => active, // for the checks
    stats: () => ({ frames: stats.frames, avg_ms: +(stats.ms / Math.max(1, stats.frames)).toFixed(2), max_ms: +stats.max.toFixed(2), lite }) };
  return { resume, pause };
}
