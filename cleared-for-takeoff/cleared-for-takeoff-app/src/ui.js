export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const STATUS = { on_track: ['On track', 'var(--ok)'], at_risk: ['At risk', 'var(--warn)'], blocked: ['Blocked', 'var(--hot)'], no_shipment: ['No shipment', 'var(--none)'] };
export const SEV = { critical: 'var(--hot)', high: '#ff8a5c', medium: 'var(--warn)', low: 'var(--none)' };
export const fmtDate = s => s ? new Date(s.length === 10 ? s + 'T12:00' : s).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—';
export function ago(iso) { const m = (Date.now() - new Date(iso)) / 6e4; return m < 60 ? `${Math.max(1, m | 0)}m ago` : m < 1440 ? `${(m / 60) | 0}h ago` : `${(m / 1440) | 0}d ago`; }
export const loading = (label = 'Loading') => `<div class="state"><span class="spin"></span>${label}…</div>`;
export const empty = msg => `<div class="state">${esc(msg)}</div>`;
export const errorState = (err, retryId) => `<div class="state err">Couldn’t load: ${esc(err.message)} <button class="chip" id="${retryId}">Retry</button></div>`;
/** Run an async loader into an element with loading / empty / error states. */
export async function load(el, fn, render, { emptyMsg = 'Nothing here yet.', label } = {}) {
  el.innerHTML = loading(label);
  try { const d = await fn(); el.innerHTML = (Array.isArray(d) && !d.length) ? empty(emptyMsg) : ''; if (!(Array.isArray(d) && !d.length)) render(d); return d; }
  catch (e) { console.warn(e); const id = 'r' + Math.random().toString(36).slice(2); el.innerHTML = errorState(e, id); $('#' + id).onclick = () => load(el, fn, render, { emptyMsg, label }); }
}
export function burst(x = innerWidth / 2, y = innerHeight / 2) { const w = $('#wipe'); w.style.setProperty('--wx', x + 'px'); w.style.setProperty('--wy', y + 'px'); w.classList.remove('go'); void w.offsetWidth; w.classList.add('go'); }
export function initCursor() {
  const c = $('#cur'); let mx = innerWidth / 2, my = innerHeight / 2, cx = mx, cy = my;
  addEventListener('mousemove', e => { document.body.classList.add('moved'); mx = e.clientX; my = e.clientY; });
  document.addEventListener('mouseover', e => c.classList.toggle('mid', !!e.target.closest('button,a,.tile,.wcard,.citem,input')));
  (function f() { cx += (mx - cx) * .18; cy += (my - cy) * .18; c.style.transform = `translate(${cx}px,${cy}px)`; document.documentElement.style.setProperty('--lx', mx / innerWidth * 100 + '%'); document.documentElement.style.setProperty('--ly', my / innerHeight * 100 + '%'); requestAnimationFrame(f); })();
  return { get mx() { return mx; }, get my() { return my; } };
}
