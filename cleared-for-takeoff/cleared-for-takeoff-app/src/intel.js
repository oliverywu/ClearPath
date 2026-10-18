// Live shipment intelligence panel inside the shipment-tracking map: route progression, tracker,
// NASA FIRMS detections and potential-disruption segments. Google Maps JS when a browser key exists,
// otherwise a lightweight SVG map with the same layers.
import { $, $$, esc } from './ui.js';
import { loadGoogleMaps, DARK_STYLE, USE_DARK_MAP, MAP_UI } from './map.js';
import { mountEmbed } from './embed-map.js';
import { getLiveShipments, getShipmentIntel } from './api.js';
const C = { traveled: '#eceae4', remaining: 'rgba(236,234,228,.38)', risk: '#ff4d2e', fire: '#ff9d45', alt: '#6fb3ff', tracker: '#5fe0a8' };
const et = iso => iso ? new Date(iso).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' ET' : '—';
const dur = s => { if (s == null) return '—'; const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return h ? `${h}h ${m}m` : `${m}m`; };
const FIRMS_MSG = { ok: 'NASA FIRMS live', empty: 'NASA FIRMS: no detections in area', stale: 'NASA FIRMS data outdated', no_key: 'NASA FIRMS key not set', error: 'NASA FIRMS unavailable' };
let state = { id: null, demo: false, timer: null, view: null };
// Key rejected after the JS map was built → switch the open panel to the embed + overlay view.
document.addEventListener('gmaps-auth-failure', () => { if (!state.id || !$('#imap')) return; state.view = null; $('#imap').innerHTML = ''; refresh(); });

const card = s => `<button class="ti2" role="listitem" data-id="${esc(s.id)}" style="--c:${STATUS_C[s.status] || 'var(--ok)'}"><i></i><span><b>${esc(s.label)}<s class="ldot" title="Live route view"></s></b><small>${esc(s.statusLabel || `${s.origin} → ${s.destination}`)}</small></span><em>${s.slackDays ?? '—'}d</em></button>`;
const STATUS_C = { on_track: 'var(--ok)', at_risk: 'var(--warn)', blocked: 'var(--hot)', no_shipment: 'var(--none)' };
/** Every shipment card in the tracking list opens the route/progress/fire panel over the map. */
export async function attachLiveShipments() {
  const list = await getLiveShipments().catch(() => []);
  const tl = $('#tlist'); if (!list.length || !tl) return;
  const have = new Set($$('#tlist .ti2').map(b => b.dataset.id));
  tl.insertAdjacentHTML('afterbegin', list.filter(s => !have.has(s.id)).map(card).join(''));
  const ids = new Set(list.map(s => s.id));
  $$('#tlist .ti2').forEach(b => { if (!ids.has(b.dataset.id)) return;
    if (!b.querySelector('.ldot')) b.querySelector('b')?.insertAdjacentHTML('beforeend', '<s class="ldot" title="Live route view"></s>');
    // Keep the original handler (map select + detailed milestone timeline drawer) and add the route panel.
    const orig = b.onclick;
    b.onclick = e => { orig?.call(b, e); $$('#tlist .ti2').forEach(x => x.classList.toggle('sel', x === b)); open(b.dataset.id); }; });
}
function shell() {
  let el = $('#intel');
  if (el) return el;
  $('#map').insertAdjacentHTML('beforeend', `<div class="intel" id="intel" hidden><div class="imap" id="imap"></div>
    <div class="ihead"><span class="ichip" id="ilabel">—</span><button class="ichip btnc" id="idemo" aria-pressed="false">Demo mode</button><button class="ichip btnc" id="ix" aria-label="Close live shipment">×</button></div>
    <div class="ipop" id="ipop" hidden></div><div class="istrip" id="istrip"><span class="spin"></span>Loading route…</div></div>`);
  el = $('#intel');
  $('#ix').onclick = () => { close(); $$('#tlist .ti2').forEach(x => x.classList.remove('sel')); };
  $('#idemo').onclick = () => { state.demo = !state.demo; $('#idemo').classList.toggle('on', state.demo); $('#idemo').setAttribute('aria-pressed', state.demo); refresh(); schedule(); };
  return el;
}
function open(id) { shell().hidden = false; state.id = id; state.view = null; $('#imap').innerHTML = ''; $('#ipop').hidden = true; refresh(); schedule(); }
function close() { const el = $('#intel'); if (el) el.hidden = true; clearInterval(state.timer); state.id = null; }
function schedule() { clearInterval(state.timer); state.timer = setInterval(refresh, state.demo ? 5000 : 60000); }
async function refresh() {
  const id = state.id; if (!id) return;
  try { const d = await getShipmentIntel(id, { demo: state.demo }); if (state.id !== id) return; render(d); }
  catch (e) { $('#istrip').innerHTML = `<span class="err">Couldn’t load ${esc(id)}: ${esc(e.message)}</span>`; }
}
function render(d) {
  const t = d.tracker, f = d.firms, open = d.warnings.filter(w => w.status !== 'resolved');
  $('#ilabel').innerHTML = `<b>${esc(d.shipment.label || d.shipment.id)}</b> · <span class="${t.isLive ? 'ok' : 'est'}">${esc(t.label)}</span>${d.route.estimatedPath ? ' · <span class="est">estimated air/sea path</span>' : ''}${d.route.fallbackReason ? ` · <small class="est" style="opacity:.75">${esc(d.route.fallbackReason)}</small>` : ''}`;
  $('#ilabel').title = [t.note, d.shipment.scheduleNote].filter(Boolean).join(' ');
  const ms = d.shipment.milestones;
  const stops = ms?.length ? ms.map(m => `<span class="st-${esc(m.state)}" title="${esc(m.label)} · ${esc(m.state)}"><i></i>${esc(m.label.split(' · ')[0])}</span>`).join('') : t.stops.map(s => `<span class="st-${s.state}" title="${esc(s.name)} · ${s.state}"><i></i>${esc(s.name.split(/[,(]/)[0])}</span>`).join('');
  $('#istrip').innerHTML = `<div class="irow"><span><b>${Math.round(t.progress * 100)}%</b> traveled</span><span><b>${Math.round(t.remainingKm)} km</b> · ${dur(t.remainingSec)} left</span><span>ETA <b>${et(t.eta)}</b></span>
    <span class="fstat f-${f.status}" title="${esc(f.message || '')}${f.errors?.length ? ' ' + esc(f.errors.join('; ')) : ''}">${FIRMS_MSG[f.status] || esc(f.status)} · ${d.fires.length} in ${f.corridorKm} km corridor</span>
    ${open.length ? `<a class="wlink" href="#/warnings/${esc(open[0].id)}">${open.length} potential disruption${open.length > 1 ? 's' : ''} →</a>` : ''}</div><div class="istops">${stops}</div>`;
  draw(d);
}
function popFire(fr, d) {
  const ev = d.events.find(e => e.fireIds?.includes(fr.id)), w = ev && d.warnings.find(x => x.fire?.eventId === ev.id && x.status !== 'resolved');
  const p = $('#ipop'); p.hidden = false;
  p.innerHTML = `<button class="dx" id="ipx" aria-label="Close">×</button><div class="k" style="color:${C.fire}">Satellite fire detection · ${esc(fr.risk)} risk</div>
  <dl><dt>Coordinates</dt><dd>${fr.lat.toFixed(4)}, ${fr.lng.toFixed(4)}</dd><dt>From route</dt><dd>${fr.distanceKm.toFixed(1)} km ${fr.ahead ? 'ahead' : '(already passed)'}</dd>
  <dt>Observed</dt><dd>${et(fr.observedAt)}${fr.outdated ? ' (outdated)' : ''}</dd><dt>Confidence</dt><dd>${esc(fr.confidence)}</dd><dt>FRP</dt><dd>${fr.frpMW != null ? fr.frpMW + ' MW' : '—'}</dd>
  <dt>Sensor</dt><dd>${esc([fr.instrument, fr.satellite, fr.source].filter(Boolean).join(' · '))}</dd>${ev ? `<dt>Segment</dt><dd>${esc(ev.segment.label)}</dd>` : ''}</dl>
  <p class="note">Potential disruption. NASA FIRMS detects heat, not road closures; confirm with traffic/DOT data.</p>${w ? `<a class="wlink" href="#/warnings/${esc(w.id)}">Open warning →</a>` : ''}`;
  $('#ipx').onclick = () => { p.hidden = true; };
}
async function draw(d) {
  if (state.view?.update) { state.view.update(d); return; }
  try {
    const g = await loadGoogleMaps(); state.view = gmapView(g, $('#imap'), d);
  } catch { state.view = embedView($('#imap'), d); }
}
function gmapView(g, el, d) {
  const map = new g.Map(el, { ...(USE_DARK_MAP ? { styles: DARK_STYLE, backgroundColor: '#07070a' } : {}), ...MAP_UI });
  // Colours tuned for the light standard Google map (the SVG fallback keeps the dark palette C).
  const G = USE_DARK_MAP ? { ...C, hollow: '#0b0b0f', halo: '#07070a' } : { ...C, traveled: '#1a73e8', remaining: '#3c4043', hollow: '#ffffff', halo: '#ffffff' };
  const info = new g.InfoWindow();
  let layers = [];
  const dashed = { icons: [{ icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 2, strokeColor: G.remaining }, offset: '0', repeat: '10px' }], strokeOpacity: 0 };
  class Tracker extends g.OverlayView { constructor() { super(); this.div = document.createElement('div'); this.div.className = 'itrk'; } onAdd() { this.getPanes().overlayMouseTarget.appendChild(this.div); } draw() { const p = this.getProjection()?.fromLatLngToDivPixel(new g.LatLng(this.pos)); if (p) { this.div.style.left = p.x + 'px'; this.div.style.top = p.y + 'px'; } } onRemove() { this.div.remove(); } }
  const trk = new Tracker(); trk.setMap(map);
  let fitted = false;
  function update(d) {
    layers.forEach(l => l.setMap(null)); layers = [];
    const add = l => (layers.push(l), l);
    const geo = !!d.route.estimatedPath;
    add(new g.Polyline({ map, path: d.route.remaining, geodesic: geo, strokeWeight: 3, ...dashed }));
    add(new g.Polyline({ map, path: d.route.traveled, geodesic: geo, strokeColor: G.halo, strokeWeight: 7, strokeOpacity: .9 }));
    add(new g.Polyline({ map, path: d.route.traveled, geodesic: geo, strokeColor: G.traveled, strokeWeight: 3.5, strokeOpacity: .95 }));
    d.events.filter(e => e.alt?.path).forEach(e => add(new g.Polyline({ map, path: e.alt.path, strokeColor: C.alt, strokeWeight: 2, strokeOpacity: .6 })));
    d.events.filter(e => ['medium', 'high'].includes(e.risk) && !e.outdated).forEach(e => add(new g.Polyline({ map, path: e.segment.path, strokeColor: C.risk, strokeWeight: 6, strokeOpacity: .85, zIndex: 5 })));
    const dot = (pos, fill, stroke, scale, title) => add(new g.Marker({ map, position: pos, title, zIndex: 8, icon: { path: g.SymbolPath.CIRCLE, scale, fillColor: fill, fillOpacity: 1, strokeColor: stroke, strokeWeight: 2 } }));
    d.tracker.stops.forEach(s => { const m = dot(s, s.state === 'completed' ? G.traveled : G.hollow, s.kind === 'border' ? G.alt : G.traveled, s.kind === 'origin' || s.kind === 'destination' ? 6 : 4.5, `${s.name} · ${s.state}`);
      // Stops are planned checkpoints; whether one is passed is estimated from the schedule unless GPS is live.
      m.addListener('click', () => { const when = s.at ? ` · ${new Date(s.at).toLocaleString()}` : ''; info.setContent(`<div style="color:#202124;font:13px system-ui"><b>${esc(s.name)}</b><br>${esc(s.kind)} · ${esc(s.state)}${esc(when)}${d.tracker.isLive ? '' : '<br><i>Passed/upcoming state estimated from schedule</i>'}</div>`); info.open({ map, anchor: m }); map.panTo(s); map.setZoom(Math.max(map.getZoom(), 9)); }); });
    d.fires.forEach(fr => { const m = add(new g.Marker({ map, position: fr, title: `Fire detection · ${fr.distanceKm.toFixed(1)} km from route`, zIndex: 10, icon: { path: g.SymbolPath.FORWARD_CLOSED_ARROW, rotation: 0, scale: 3.2, fillColor: fr.outdated ? '#6d6d78' : C.fire, fillOpacity: 1, strokeColor: G.halo, strokeWeight: 1 } })); m.addListener('click', () => popFire(fr, d)); });
    trk.pos = d.tracker.position; trk.div.classList.toggle('est', !d.tracker.isLive); trk.div.title = d.tracker.label; trk.draw();
    if (!fitted) { const b = new g.LatLngBounds(); [...d.route.traveled, ...d.route.remaining].forEach(p => b.extend(p)); map.fitBounds(b, 40); fitted = true; }
  }
  update(d); return { update };
}
function unwrap(d) { // keep longitudes continuous across the antimeridian for the flat SVG map
  let prev = null; const fix = p => { let lng = p.lng; if (prev !== null) while (lng - prev > 180) lng -= 360; if (prev !== null) while (prev - lng > 180) lng += 360; prev = lng; return { ...p, lng }; };
  const traveled = d.route.traveled.map(fix), remaining = d.route.remaining.map(fix), path = [...traveled, ...remaining];
  const near = p => { const ref = path.reduce((a, q) => Math.abs(q.lat - p.lat) < Math.abs(a.lat - p.lat) ? q : a, path[0]); let lng = p.lng; while (lng - ref.lng > 180) lng -= 360; while (ref.lng - lng > 180) lng += 360; return { ...p, lng }; };
  return { ...d, route: { ...d.route, traveled, remaining }, fires: d.fires.map(near), tracker: { ...d.tracker, position: near(d.tracker.position), stops: d.tracker.stops.map(near) }, events: d.events.map(e => ({ ...e, segment: { ...e.segment, path: e.segment.path.map(near) } })) };
}
function svgView(el, d0) {
  const d = unwrap(d0);
  const all = [...d.route.traveled, ...d.route.remaining, ...d.fires];
  const lat0 = all.reduce((a, p) => a + p.lat, 0) / all.length, k = Math.cos(lat0 * Math.PI / 180);
  const xs = all.map(p => p.lng * k), ys = all.map(p => -p.lat), minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const W = 1000, H = 640, pad = 50, s = Math.min((W - 2 * pad) / (maxX - minX || 1), (H - 2 * pad) / (maxY - minY || 1));
  const ox = (W - s * (maxX - minX)) / 2, oy = (H - s * (maxY - minY)) / 2;
  const P = p => [ox + (p.lng * k - minX) * s, oy + (-p.lat - minY) * s];
  const path = pts => pts.map((p, i) => (i ? 'L' : 'M') + P(p).map(v => v.toFixed(1)).join(' ')).join('');
  function update(dRaw) {
    const d = unwrap(dRaw);
    const risk = d.events.filter(e => ['medium', 'high'].includes(e.risk) && !e.outdated);
    const [tx, ty] = P(d.tracker.position);
    el.innerHTML = `<svg class="isvg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Route map for ${esc(d.shipment.id)}">
      <path d="${path(d.route.remaining)}" stroke="${C.remaining}" stroke-width="3" stroke-dasharray="6 7" fill="none"/>
      <path d="${path(d.route.traveled)}" stroke="${C.traveled}" stroke-width="3.5" fill="none"/>
      ${d.events.filter(e => e.alt?.path).map(e => `<path d="${path(e.alt.path)}" stroke="${C.alt}" stroke-width="2" opacity=".6" fill="none"/>`).join('')}
      ${risk.map(e => `<path d="${path(e.segment.path)}" stroke="${C.risk}" stroke-width="7" opacity=".85" stroke-linecap="round" fill="none"/>`).join('')}
      ${d.tracker.stops.map(st => { const [x, y] = P(st); return `<g><circle cx="${x}" cy="${y}" r="${st.kind === 'origin' || st.kind === 'destination' ? 6 : 4.5}" fill="${st.state === 'completed' ? C.traveled : '#0b0b0f'}" stroke="${st.kind === 'border' ? C.alt : C.traveled}" stroke-width="2"><title>${esc(st.name)} · ${st.state}</title></circle><text x="${x + 9}" y="${y + 4}" class="slab">${esc(st.name.split(/[,(]/)[0])}</text></g>`; }).join('')}
      ${d.fires.map((fr, i) => { const [x, y] = P(fr); return `<path data-fire="${i}" d="M${x} ${y - 7} L${x + 5} ${y + 4} L${x - 5} ${y + 4}Z" fill="${fr.outdated ? '#6d6d78' : C.fire}" stroke="#07070a"><title>Fire detection · ${fr.distanceKm.toFixed(1)} km from route</title></path>`; }).join('')}
      <circle cx="${tx}" cy="${ty}" r="9" class="strk ${d.tracker.isLive ? '' : 'est'}"><title>${esc(d.tracker.label)}</title></circle><circle cx="${tx}" cy="${ty}" r="3.5" fill="${C.tracker}"/>
    </svg><span class="mapchip">${d.route.distanceMeters ? Math.round(d.route.distanceMeters / 1000) + ' km ' + (d.route.estimatedPath ? 'great-circle · ' : 'Google route · ') : ''}${d.route.estimatedPath ? 'estimated air/sea path' : 'schematic map'}</span>`;
    $$('[data-fire]', el).forEach(n => n.addEventListener('click', () => popFire(d.fires[+n.dataset.fire], d)));
  }
  update(d); return { update };
}

/** Keyless Google Maps embed with route, tracker and fire markers drawn on top (Web Mercator, approximate). */
function embedView(el, d0) {
  let d = unwrap(d0); el.innerHTML = '';
  const line = (P, pts) => pts.map((p, i) => (i ? 'L' : 'M') + P(p).map(v => v.toFixed(1)).join(' ')).join('');
  const v = mountEmbed(el, { title: `Google Map for ${esc(d.shipment.id)}`,
    note: `${d.route.distanceMeters ? Math.round(d.route.distanceMeters / 1000) + ' km · ' : ''}${d.route.estimatedPath ? 'estimated path · ' : ''}approximate overlay`,
    render: P => { const risk = d.events.filter(e => ['medium', 'high'].includes(e.risk) && !e.outdated), [tx, ty] = P(d.tracker.position);
      return `<path d="${line(P, d.route.remaining)}" stroke="${C.remaining}" stroke-width="3" stroke-dasharray="6 7" fill="none"/>
      <path d="${line(P, d.route.traveled)}" stroke="${C.traveled}" stroke-width="3.5" fill="none"/>
      ${d.events.filter(e => e.alt?.path).map(e => `<path d="${line(P, e.alt.path)}" stroke="${C.alt}" stroke-width="2" opacity=".6" fill="none"/>`).join('')}
      ${risk.map(e => `<path d="${line(P, e.segment.path)}" stroke="${C.risk}" stroke-width="7" opacity=".85" stroke-linecap="round" fill="none"/>`).join('')}
      ${d.tracker.stops.map(st => { const [x, y] = P(st); return `<circle cx="${x}" cy="${y}" r="${st.kind === 'origin' || st.kind === 'destination' ? 5 : 3.5}" fill="${st.state === 'completed' ? C.traveled : '#0b0b0f'}" stroke="${st.kind === 'border' ? C.alt : C.traveled}" stroke-width="2" class="ehot"><title>${esc(st.name)} · ${st.state}</title></circle>`; }).join('')}
      ${d.fires.map((fr, i) => { const [x, y] = P(fr); return `<path data-fire="${i}" class="ehot" d="M${x} ${y - 7} L${x + 5} ${y + 4} L${x - 5} ${y + 4}Z" fill="${fr.outdated ? '#6d6d78' : C.fire}" stroke="#07070a"><title>Fire detection · ${fr.distanceKm.toFixed(1)} km from route</title></path>`; }).join('')}
      <circle cx="${tx}" cy="${ty}" r="9" class="strk ehot ${d.tracker.isLive ? '' : 'est'}"><title>${esc(d.tracker.label)}</title></circle><circle cx="${tx}" cy="${ty}" r="3.5" fill="${C.tracker}"/>`; },
    bind: svg => svg.querySelectorAll('[data-fire]').forEach(n => n.addEventListener('click', () => popFire(d.fires[+n.dataset.fire], d))) });
  const pts = () => [...d.route.traveled, ...d.route.remaining];
  v.setView(pts());
  return { update(n) { d = unwrap(n); v.redraw(); } };
}
