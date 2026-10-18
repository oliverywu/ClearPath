// Google Maps tracking view. Loads the Maps JavaScript API with the key from config; any failure → reject (caller shows the SVG fallback).
import { GOOGLE_MAPS_API_KEY, LOAD_LOCAL_CONFIG } from './config.js';
async function resolveKey() {
  if (LOAD_LOCAL_CONFIG) { try { const m = await import('./config.local.js'); if (m.GOOGLE_MAPS_API_KEY) return m.GOOGLE_MAPS_API_KEY; } catch {} }
  // Optional browser (referrer-restricted) key served by the backend from GOOGLE_MAPS_BROWSER_KEY.
  try { const r = await fetch('/api/maps-config'); if (r.ok) { const { browserKey } = await r.json(); if (browserKey) return browserKey; } } catch {}
  return GOOGLE_MAPS_API_KEY;
}
let loading;
export function loadGoogleMaps() {
  if (window.__cftMapsRejected) return Promise.reject(new Error('KEY_REJECTED'));
  if (window.google?.maps?.Map) return Promise.resolve(window.google.maps); // already loaded (or a test stub)
  return loading ||= (async () => {
    const key = await resolveKey();
    if (!key) throw new Error('NO_KEY');
    return new Promise((res, rej) => {
      const done = setTimeout(() => rej(new Error('Google Maps load timed out')), 12000);
      window.__cftMapsReady = () => { clearTimeout(done); res(window.google.maps); };
      window.gm_authFailure = () => { window.__cftMapsRejected = true; loading = Promise.reject(new Error('KEY_REJECTED')); loading.catch(() => {}); clearTimeout(done); rej(new Error('KEY_REJECTED')); document.dispatchEvent(new CustomEvent('gmaps-auth-failure')); };
      const s = document.createElement('script');
      s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&libraries=geometry&callback=__cftMapsReady`;
      s.async = true; s.onerror = () => { clearTimeout(done); rej(new Error('Google Maps failed to load')); };
      document.head.appendChild(s);
    });
  })();
}
export const DARK_STYLE = [
  { elementType: 'geometry', stylers: [{ color: '#0b0b0f' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#6b6b74' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#07070a' }] },
  { elementType: 'labels.icon', stylers: [{ visibility: 'off' }] },
  { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: '#24242c' }] },
  { featureType: 'administrative.country', elementType: 'labels.text.fill', stylers: [{ color: '#8a8a93' }] },
  { featureType: 'administrative.locality', stylers: [{ visibility: 'off' }] },
  { featureType: 'poi', stylers: [{ visibility: 'off' }] },
  { featureType: 'road', stylers: [{ visibility: 'off' }] },
  { featureType: 'transit', stylers: [{ visibility: 'off' }] },
  { featureType: 'landscape', elementType: 'geometry', stylers: [{ color: '#111116' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#050507' }] },
  { featureType: 'water', elementType: 'labels.text.fill', stylers: [{ color: '#2a2a30' }] },
];
const lerp = (a, b, t) => ({ lat: a.lat + (b.lat - a.lat) * t, lng: a.lng + (b.lng - a.lng) * t });
/** Build the map. list = TrackingSummary[] with coords; color(s) → CSS colour; onSelect(id) opens the drawer. Returns { select(id), draw() }. */
export function buildMap(g, el, list, color, onSelect) {
  const map = new g.Map(el, { center: { lat: 30, lng: 20 }, zoom: 2, minZoom: 2, styles: DARK_STYLE, disableDefaultUI: true, zoomControl: true, backgroundColor: '#07070a', gestureHandling: 'cooperative', keyboardShortcuts: false });
  const sph = g.geometry?.spherical;
  const along = (a, b, t) => sph ? (p => ({ lat: p.lat(), lng: p.lng() }))(sph.interpolate(new g.LatLng(a), new g.LatLng(b), t)) : lerp(a, b, t);
  class Pulse extends g.OverlayView {
    constructor(pos, c, id) { super(); this.pos = pos; this.div = document.createElement('div'); this.div.className = 'gpulse'; this.div.style.setProperty('--c', c); this.div.title = id; this.div.onclick = e => { e.stopPropagation(); onSelect(id); }; }
    onAdd() { this.getPanes().overlayMouseTarget.appendChild(this.div); }
    draw() { const p = this.getProjection()?.fromLatLngToDivPixel(new g.LatLng(this.pos)); if (p) { this.div.style.left = p.x + 'px'; this.div.style.top = p.y + 'px'; } }
    onRemove() { this.div.remove(); }
  }
  const items = list.map(s => {
    const c = color(s), { origin, destination, current } = s.coords;
    const line = new g.Polyline({ map, path: [origin], geodesic: true, strokeColor: c, strokeOpacity: .9, strokeWeight: 2 });
    const dot = pos => new g.Marker({ map, position: pos, clickable: true, title: `${s.countryName} · ${s.id}`, icon: { path: g.SymbolPath.CIRCLE, scale: 4, fillColor: '#0b0b0f', fillOpacity: 1, strokeColor: c, strokeWeight: 2 } });
    const mo = dot(origin), md = dot(destination); [mo, md, line].forEach(o => o.addListener('click', () => onSelect(s.id)));
    const pulse = new Pulse(current, c, s.id); pulse.setMap(map);
    return { s, line, origin, destination };
  });
  let drawn = false;
  function draw() { // animate geodesic polylines origin → destination
    if (drawn) return; drawn = true; const t0 = performance.now(), D = 1600;
    (function f(t) { const k = Math.min(1, (t - t0) / D), e = 1 - Math.pow(1 - k, 3);
      items.forEach((it, i) => { const ki = Math.max(0, Math.min(1, e * 1.3 - i * .06)), n = Math.max(2, Math.round(ki * 48)), pts = [];
        for (let j = 0; j <= n; j++) pts.push(along(it.origin, it.destination, ki * j / n)); it.line.setPath(pts); });
      if (k < 1) requestAnimationFrame(f); })(t0);
  }
  function select(id) { const it = items.find(x => x.s.id === id); if (!it) return;
    const b = new g.LatLngBounds(); [it.origin, it.destination, it.s.coords.current].forEach(p => b.extend(p)); map.fitBounds(b, 60);
    items.forEach(x => x.line.setOptions({ strokeWeight: x === it ? 3.5 : 2, strokeOpacity: x === it ? 1 : .35 })); }
  return { map, draw, select };
}
