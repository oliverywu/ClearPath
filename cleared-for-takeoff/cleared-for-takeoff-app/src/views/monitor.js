import { $, esc, load, loading, errorState } from '../ui.js';
import { getShipments } from '../api.js';
import { analyzeShipmentRoute } from '../api.js';
export async function renderMonitor(root) {
  if (!root.dataset.ready) {
    root.dataset.ready = '1';
    root.innerHTML = `<div class="vhead"><a class="back" href="#/">← Landing</a><div class="k">Live route intelligence</div><h2>Disaster <em>monitor.</em></h2>
      <p class="l">GDACS alerts near the calculated shipment route. Events elsewhere are excluded.</p></div>
      <div class="monitor-controls"><label>Shipment<select id="monitor-shipment"><option>Loading shipments…</option></select></label>
      <label>Proximity<select id="monitor-radius"><option value="25">25 km</option><option value="50" selected>50 km</option><option value="100">100 km</option><option value="250">250 km</option></select></label>
      <button class="btn" id="monitor-run">Analyze route</button></div>
      <div id="monitor-result" class="monitor-result"><div class="state">Select a shipment and analyze its route.</div></div>`;
    const select = $('#monitor-shipment', root);
    await load(select, getShipments, shipments => {
      select.innerHTML = shipments.length ? shipments.map(s => `<option value="${esc(s.id)}">${esc(s.id)} · ${esc(s.origin)} → ${esc(s.destination)} · ${esc(s.study)}</option>`).join('') : '<option value="">No shipments available</option>';
      $('#monitor-run', root).disabled = !shipments.length;
    }, { emptyMsg: 'No shipments available.', label: 'Loading shipments' });
    $('#monitor-run', root).onclick = analyze;
    select.addEventListener('change', analyze);
    $('#monitor-radius', root).addEventListener('change', analyze);
  }

  async function analyze() {
    const result = $('#monitor-result', root), shipmentId = $('#monitor-shipment', root).value;
    const shipment = (await getShipments()).find(s => s.id === shipmentId);
    if (!shipment) { result.innerHTML = '<div class="state">No shipment selected.</div>'; return; }
    result.innerHTML = loading('Calculating Google Maps route and checking GDACS alerts');
    try {
      const proximityKm = Number($('#monitor-radius', root).value) || 50;
      const analysis = await analyzeShipmentRoute({ origin: shipment.origin, destination: shipment.destination, proximityKm });
      const nearby = analysis.events || [];
      const routeKm = analysis.distanceMeters ? Math.round(analysis.distanceMeters / 1000).toLocaleString() : '—';
      result.innerHTML = `<div class="monitor-summary"><div><div class="k">${esc(shipment.id)} · ${esc(shipment.study)}</div><h3>${esc(shipment.origin)} <em>→</em> ${esc(shipment.destination)}</h3></div><div class="route-stat"><b>${routeKm} km</b><span>Google Maps route</span></div></div>
        <div class="monitor-meta">Checked ${analysis.eventsChecked} recent GDACS events · ${proximityKm} km route corridor · updated ${new Date(analysis.analyzedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
        ${nearby.length ? `<div class="threat-list">${nearby.map(e => `<article class="threat threat-${e.severity}"><span class="threat-dot"></span><div><div class="threat-title">${esc(e.title)}</div><div class="threat-meta">${esc(e.type)} · ${esc(e.country)} · ${e.severity} alert</div>${e.details ? `<p>${esc(e.details)}</p>` : ''}</div><div class="threat-distance"><b>${Math.round(e.distanceKm)} km</b><span>from route</span>${e.date && Number.isFinite(+e.date) ? `<time>${e.date.toLocaleDateString()}</time>` : ''}</div></article>`).join('')}</div>` : '<div class="state clear-state">No recent GDACS events intersect this route corridor.</div>'}`;
    } catch (error) {
      result.innerHTML = errorState(error, 'monitor-retry');
      $('#monitor-retry', root).onclick = analyze;
    }
  }
}
