// Keyless Google Maps embed (no API key) with an SVG overlay projected in Web Mercator to match the
// embed's center/zoom. Used whenever the Maps JavaScript API key is missing, rejected or fails to load.
// The iframe is static (pointer-events:none) so the overlay stays aligned; only overlay shapes are clickable.
const TILE = 256, MAXLAT = 85.05112878;
const wx = lng => (lng + 180) / 360 * TILE;
const wy = lat => { const s = Math.sin(Math.max(-MAXLAT, Math.min(MAXLAT, lat)) * Math.PI / 180); return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * TILE; };
const unproj = y => { const n = Math.PI - 2 * Math.PI * y / TILE; return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n))); };
/** Keep longitudes continuous (no antimeridian jumps) along a sequence of points. */
export function continuous(pts) { let prev = null; return pts.map(p => { let lng = p.lng; if (prev !== null) { while (lng - prev > 180) lng -= 360; while (prev - lng > 180) lng += 360; } prev = lng; return { ...p, lng }; }); }
/** Integer zoom + center that fits all points into w×h px (embed supports integer zoom only). */
export function fitView(points, w, h, pad = 40) {
  if (!points.length) return { center: { lat: 30, lng: 20 }, zoom: 2 };
  const xs = points.map(p => wx(p.lng)), ys = points.map(p => wy(p.lat));
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const z = Math.floor(Math.log2(Math.min((w - 2 * pad) / Math.max(x1 - x0, 1e-6), (h - 2 * pad) / Math.max(y1 - y0, 1e-6))));
  const zoom = Math.max(1, Math.min(14, z));
  return { center: { lat: unproj((y0 + y1) / 2), lng: (x0 + x1) / 2 / TILE * 360 - 180 }, zoom };
}
/** lat/lng → pixel inside a w×h viewport centered on view.center at view.zoom. */
export function project(p, view, w, h) {
  const k = 2 ** view.zoom; let lng = p.lng; while (lng - view.center.lng > 180) lng -= 360; while (view.center.lng - lng > 180) lng += 360;
  return [w / 2 + (wx(lng) - wx(view.center.lng)) * k, h / 2 + (wy(p.lat) - wy(view.center.lat)) * k];
}
const norm = lng => ((lng + 540) % 360) - 180;
export const embedSrc = v => `https://maps.google.com/maps?ll=${v.center.lat.toFixed(5)},${norm(v.center.lng).toFixed(5)}&z=${v.zoom}&t=m&ie=UTF8&iwloc=&output=embed`;
/** Great-circle interpolation (for overseas legs) → n+1 points. */
export function greatCircle(a, b, n = 48) {
  const r = Math.PI / 180, [p1, l1, p2, l2] = [a.lat * r, a.lng * r, b.lat * r, b.lng * r];
  const d = 2 * Math.asin(Math.sqrt(Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin((l2 - l1) / 2) ** 2));
  if (d < 1e-9) return [a, b];
  const out = []; for (let i = 0; i <= n; i++) { const f = i / n, A = Math.sin((1 - f) * d) / Math.sin(d), B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(p1) * Math.cos(l1) + B * Math.cos(p2) * Math.cos(l2), y = A * Math.cos(p1) * Math.sin(l1) + B * Math.cos(p2) * Math.sin(l2), z = A * Math.sin(p1) + B * Math.sin(p2);
    out.push({ lat: Math.atan2(z, Math.hypot(x, y)) / r, lng: Math.atan2(y, x) / r }); }
  return continuous(out);
}
/**
 * Mount an embed + overlay in el. render(P, w, h) returns SVG inner markup, P = latlng→[x,y].
 * Returns { setView(points), redraw(), view }.
 */
export function mountEmbed(el, { title = 'Google Map', note = 'Approximate overlay', render, bind }) {
  el.classList.add('emap');
  el.insertAdjacentHTML('afterbegin', `<iframe class="eframe" title="${title}" loading="lazy" referrerpolicy="no-referrer-when-downgrade" tabindex="-1" aria-hidden="true"></iframe><svg class="eover" xmlns="http://www.w3.org/2000/svg"></svg><span class="mapchip">${note}</span>`);
  const f = el.querySelector('.eframe'), svg = el.querySelector('.eover');
  let pts = [], view = null, src = '';
  const size = () => { const r = el.getBoundingClientRect(); return [Math.round(r.width) || 800, Math.round(r.height) || 560]; };
  function redraw() {
    const [w, h] = size(); view = fitView(pts, w, h);
    const s = embedSrc(view); if (s !== src) { src = s; f.src = s; }
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('width', w); svg.setAttribute('height', h);
    svg.innerHTML = render(p => project(p, view, w, h), w, h); bind?.(svg);
  }
  new ResizeObserver(() => pts.length && redraw()).observe(el);
  return { setView(p) { pts = p; redraw(); }, redraw, get view() { return view; } };
}
