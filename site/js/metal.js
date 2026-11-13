// Metallic plum (DESIGN.md "reflective metallic finish"): the lighter band in each .metal panel's
// top strip drifts toward the pointer. Off for touch-only pointers and prefers-reduced-motion,
// where the band rests at its default position. Updates at most once per animation frame.
export function startMetal() {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const fine = matchMedia("(hover: hover) and (pointer: fine)");
  if (reduce.matches || !fine.matches) return;
  let x = null, frame = 0;
  const panels = () => document.querySelectorAll(".metal");
  const current = new WeakMap();
  const tick = () => {
    frame = 0;
    let moving = false;
    for (const p of panels()) {
      const r = p.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight) continue; // off-screen: skip
      const target = x === null ? 30 : Math.min(85, Math.max(15, ((x - r.left) / r.width) * 100));
      const now = current.get(p) ?? 30;
      const next = now + (target - now) * 0.12; // eased, never jumps
      current.set(p, next);
      p.style.setProperty("--mx", `${next.toFixed(1)}%`);
      if (Math.abs(target - next) > 0.2) moving = true;
    }
    if (moving) frame = requestAnimationFrame(tick);
  };
  addEventListener("pointermove", (e) => { x = e.clientX; if (!frame) frame = requestAnimationFrame(tick); }, { passive: true });
  reduce.addEventListener("change", () => { if (reduce.matches) for (const p of panels()) p.style.removeProperty("--mx"); });
}
