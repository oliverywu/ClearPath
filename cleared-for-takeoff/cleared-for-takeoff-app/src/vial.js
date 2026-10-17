// Interactive vial: lifts out of the hero hand and trails the custom cursor (+28,+28) across every view.
// Returns to the hand when the pointer is over the hand, or after ~4s idle on the landing view.
const OFF = 28, IDLE_MS = 4000;
export function initVial() {
  const fly = document.getElementById('vfly'), dock = document.getElementById('vdock'), hand = document.getElementById('img');
  if (!fly || !dock || matchMedia('(hover:none), (prefers-reduced-motion: reduce)').matches) return;
  let state = 'docked', x = 0, y = 0, vx = 0, vy = 0, rot = 0, mx = 0, my = 0, last = performance.now(), w = 0, h = 0;
  const body = document.body;
  const dockRect = () => dock.getBoundingClientRect();
  const onLanding = () => (body.dataset.view || 'landing') === 'landing' && scrollY < innerHeight * .35;
  const overHand = () => { const r = hand.getBoundingClientRect(); return onLanding() && mx > r.left && mx < r.right && my > r.top && my < r.bottom; };
  function lift() { const r = dockRect(); w = r.width; h = r.height; fly.style.width = w + 'px'; fly.style.height = h + 'px'; x = r.left; y = r.top; vx = vy = 0; state = 'flying'; body.classList.add('vdocked-off'); }
  addEventListener('pointermove', e => { if (e.pointerType === 'touch') return; mx = e.clientX; my = e.clientY; last = performance.now();
    if (state === 'docked' && !overHand()) lift();
    else if (state !== 'docked' && overHand()) state = 'returning';
    else if (state === 'returning' && !overHand()) state = 'flying'; }, { passive: true });
  (function tick(t) {
    if (state !== 'docked') {
      if (state === 'flying' && onLanding() && t - last > IDLE_MS) state = 'returning';
      let tx, ty;
      if (state === 'returning') { if (!onLanding()) state = 'flying'; const r = dockRect(); tx = r.left; ty = r.top; w += (r.width - w) * .12; h += (r.height - h) * .12; fly.style.width = w + 'px'; fly.style.height = h + 'px'; }
      if (state === 'flying') { tx = mx + OFF; ty = my + OFF; }
      const k = state === 'returning' ? .09 : .07, d = .78;
      vx = (vx + (tx - x) * k) * d; vy = (vy + (ty - y) * k) * d; x += vx; y += vy;
      rot += (Math.max(-28, Math.min(28, vx * 1.6)) - rot) * .12;
      const bob = state === 'flying' ? Math.sin(t / 520) * 4 : 0, sc = state === 'flying' ? .55 : 1;
      fly.style.transform = `translate3d(${x}px,${y + bob}px,0) rotate(${rot}deg) scale(${sc})`;
      if (state === 'returning' && Math.hypot(tx - x, ty - y) < 1.5 && Math.hypot(vx, vy) < .4) { state = 'docked'; body.classList.remove('vdocked-off'); rot = 0; }
    }
    requestAnimationFrame(tick);
  })(performance.now());
}
