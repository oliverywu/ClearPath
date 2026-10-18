import { $, esc, loading, errorState } from '../ui.js';
import { getShipments, getHistoricalRouteExamples, analyzeShipmentRoute, analyzeHistoricalRoute } from '../api.js';
export async function renderMonitor(root) {
  if (!root.dataset.ready) {
    root.dataset.ready = '1';
    root.innerHTML = `<div class="vhead"><a class="back" href="#/">← Landing</a><div class="k">Live route intelligence</div><h2>Disaster <em>monitor.</em></h2>
      <p class="l">Check recent GDACS alerts along a shipment route, or explore documented historical disaster cases.</p></div>
      <div class="monitor-controls"><label>Route or case study<select id="monitor-shipment"><option>Loading routes…</option></select></label>
      <label>Proximity<select id="monitor-radius"><option value="25">25 km</option><option value="50" selected>50 km</option><option value="100">100 km</option><option value="250">250 km</option></select></label>
      <button class="btn" id="monitor-run">Analyze route</button></div>
      <div id="monitor-result" class="monitor-result"><div class="state">Choose a shipment or a historical GDACS case study.</div></div>`;
    const select = $('#monitor-shipment', root);
    const runButton = $('#monitor-run', root);
    runButton.disabled = true;
    runButton.onclick = analyze;
    select.addEventListener('change', analyze);
    $('#monitor-radius', root).addEventListener('change', analyze);
    const [shipments, examples] = await Promise.all([
      getShipments().catch(() => []),
      getHistoricalRouteExamples().catch(() => [])
    ]);
    select.innerHTML = `${shipments.length ? `<optgroup label="Current shipments">${shipments.map(s => `<option value="shipment:${esc(s.id)}">${esc(s.id)} · ${esc(s.origin)} → ${esc(s.destination)} · ${esc(s.study)}</option>`).join('')}</optgroup>` : ''}${examples.length ? `<optgroup label="Historical GDACS case studies">${examples.map(example => `<option value="scenario:${esc(example.id)}">${esc(example.label)}</option>`).join('')}</optgroup>` : ''}` || '<option value="">No routes available</option>';
    runButton.disabled = !shipments.length && !examples.length;
    if (runButton.disabled) $('#monitor-result', root).innerHTML = '<div class="state">Routes could not be loaded.</div>';
  }

  async function analyze() {
    const result = $('#monitor-result', root), selection = $('#monitor-shipment', root).value;
    const isExample = selection.startsWith('scenario:');
    const selectedId = selection.slice(selection.indexOf(':') + 1);
    const shipment = isExample ? null : (await getShipments()).find(s => s.id === selectedId);
    if (!isExample && !shipment) { result.innerHTML = '<div class="state">No shipment selected.</div>'; return; }
    result.innerHTML = loading('Calculating Google Maps route and checking GDACS alerts');
    try {
      const proximityKm = Number($('#monitor-radius', root).value) || 50;
      const analysis = isExample
        ? await analyzeHistoricalRoute({ scenarioId: selectedId, proximityKm })
        : await analyzeShipmentRoute({ origin: shipment.origin, destination: shipment.destination, proximityKm });
      const nearby = analysis.events || [];
      const routeKm = analysis.distanceMeters ? Math.round(analysis.distanceMeters / 1000).toLocaleString() : '—';
      const caseLabel = isExample ? analysis.scenarioLabel : `${shipment.id} · ${shipment.study}`;
      const meta = isExample
        ? 'Historical case study · past GDACS event compared with current Google Maps road geometry; this is not a live alert.'
        : `Checked ${analysis.eventsChecked} recent GDACS events`;
      result.innerHTML = `<div class="monitor-summary"><div><div class="k">${esc(caseLabel)}</div><h3>${esc(analysis.origin)} <em>→</em> ${esc(analysis.destination)}</h3></div><div class="route-stat"><b>${routeKm} km</b><span>Google Maps route</span></div></div>
        <div class="monitor-meta">${meta} · ${proximityKm} km route corridor · updated ${new Date(analysis.analyzedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
        ${nearby.length ? `<div class="threat-list">${nearby.map(e => `<article class="threat threat-${e.severity}"><span class="threat-dot"></span><div><div class="threat-title">${esc(e.title)}</div><div class="threat-meta">${esc(e.type)} · ${esc(e.country)} · ${e.severity} alert</div>${e.details ? `<p>${esc(e.details)}</p>` : ''}${e.sourceUrl ? `<a class="threat-source" href="${esc(e.sourceUrl)}" target="_blank" rel="noopener noreferrer">GDACS source ↗</a>` : ''}</div><div class="threat-distance"><b>${Math.round(e.distanceKm)} km</b><span>from route</span>${e.timestamp ? `<time>${new Date(e.timestamp).toLocaleDateString()}</time>` : ''}</div></article>`).join('')}</div>` : `<div class="state clear-state">${isExample ? 'This historical event did not fall inside the selected route corridor.' : 'No recent GDACS events intersect this route corridor.'}</div>`}`;
    } catch (error) {
      result.innerHTML = errorState(error, 'monitor-retry');
      $('#monitor-retry', root).onclick = analyze;
    }
  }
}
