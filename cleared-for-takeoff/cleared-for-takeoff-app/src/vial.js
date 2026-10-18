// The vial follows the pointer over the landing hero, then parks in the lower-right corner.
const OFF = 28, IDLE_MS = 4000, CORNER_GAP = 22;
export function initVial() {
  const fly = document.getElementById('vfly'), dock = document.getElementById('vdock'), hand = document.getElementById('img');
  if (!fly || !dock || matchMedia('(hover:none), (prefers-reduced-motion: reduce)').matches) return;
  let state = 'docked', x = 0, y = 0, vx = 0, vy = 0, rot = 0, mx = 0, my = 0, last = performance.now(), w = 0, h = 0;
  const body = document.body;
  const dockRect = () => dock.getBoundingClientRect();
  const onLanding = () => (body.dataset.view || 'landing') === 'landing' && scrollY < innerHeight;
  const overHand = () => { const r = hand.getBoundingClientRect(); return onLanding() && mx > r.left && mx < r.right && my > r.top && my < r.bottom; };
  function lift() {
    const r = dockRect(); w = r.width; h = r.height;
    fly.style.width = `${w}px`; fly.style.height = `${h}px`;
    x = r.left; y = r.top; vx = vy = 0; state = 'flying'; body.classList.add('vdocked-off');
  }
  function parkInCorner() {
    if (state === 'docked') lift();
    w = 48; h = 96; fly.style.width = `${w}px`; fly.style.height = `${h}px`;
    state = 'corner';
  }
  function returnToHand() {
    if (state === 'corner') state = 'returning';
  }
  function onScroll() {
    if (onLanding()) returnToHand();
    else parkInCorner();
  }
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll, { passive: true });
  addEventListener('pointermove', e => {
    if (e.pointerType === 'touch' || !onLanding()) return;
    mx = e.clientX; my = e.clientY; last = performance.now();
    if (state === 'docked' && !overHand()) lift();
    else if (state === 'corner') state = 'flying';
    else if (state === 'returning' && !overHand()) state = 'flying';
    else if (state === 'flying' && overHand()) state = 'returning';
  }, { passive: true });
  onScroll();
  (function tick(t) {
    if (state !== 'docked') {
      if (state === 'flying' && onLanding() && t - last > IDLE_MS) state = 'returning';
      let tx, ty, targetW = w, targetH = h;
      if (state === 'returning') {
        if (!onLanding()) { parkInCorner(); }
        else {
          const r = dockRect(); tx = r.left; ty = r.top;
          targetW = r.width; targetH = r.height;
          w += (targetW - w) * .12; h += (targetH - h) * .12;
          fly.style.width = `${w}px`; fly.style.height = `${h}px`;
        }
      }
      if (state === 'corner') {
        tx = innerWidth - w - CORNER_GAP;
        ty = innerHeight - h - CORNER_GAP;
      } else if (state === 'flying') {
        tx = mx + OFF; ty = my + OFF;
      }
      const returning = state === 'returning';
      if (tx !== undefined && ty !== undefined) {
        const k = returning ? .09 : state === 'corner' ? .08 : .07, damping = .78;
        vx = (vx + (tx - x) * k) * damping; vy = (vy + (ty - y) * k) * damping; x += vx; y += vy;
        const desiredRotation = state === 'corner' ? -8 : state === 'flying' ? Math.max(-28, Math.min(28, vx * 1.6)) : 0;
        rot += (desiredRotation - rot) * .12;
        const bob = state === 'flying' ? Math.sin(t / 520) * 4 : 0;
        fly.style.transform = `translate3d(${x}px,${y + bob}px,0) rotate(${rot}deg) scale(${state === 'flying' ? .55 : 1})`;
        if (returning && Math.hypot(tx - x, ty - y) < 1.5 && Math.hypot(vx, vy) < .4) {
          state = 'docked'; body.classList.remove('vdocked-off'); rot = 0;
        }
      }
    }
    requestAnimationFrame(tick);
  })(performance.now());
}
