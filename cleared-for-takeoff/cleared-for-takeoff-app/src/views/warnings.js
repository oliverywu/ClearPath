import { $, $$, esc, SEV, ago, load, loading, errorState } from '../ui.js';
import { getWarnings, getWarning } from '../api.js';
let all = [], fSev = 'all', fStat = 'all';
export async function renderWarnings(root, id) {
  if (!root.dataset.ready) {
    root.dataset.ready = 1;
    root.innerHTML = `<div class="vhead"><a class="back" href="#/">← Landing</a><div class="k">Cleared for Takeoff · warnings</div><h2>All recent <em>warnings.</em></h2>
    <div class="invbar" id="wfilt">${['all', 'critical', 'high', 'medium', 'low'].map(s => `<button class="chip ${s === 'all' ? 'on' : ''}" data-sev="${s}">${s === 'all' ? 'Any severity' : s}</button>`).join('')}<span class="sep"></span>
    ${[['all', 'Any status'], ['open', 'Open'], ['in_review', 'In review'], ['resolved', 'Resolved']].map(([k, l]) => `<button class="chip ${k === 'all' ? 'on' : ''}" data-ws="${k}">${l}</button>`).join('')}</div></div>
    <div class="wlay"><div id="wlist" class="wlist"></div><aside id="wdetail" class="wdetail"></aside></div>`;
    $$('#wfilt .chip', root).forEach(c => c.onclick = () => { const g = c.dataset.sev ? 'sev' : 'ws'; $$(`#wfilt [data-${g}]`, root).forEach(x => x.classList.toggle('on', x === c)); if (g === 'sev') fSev = c.dataset.sev; else fStat = c.dataset.ws; list(); });
    await load($('#wlist', root), getWarnings, d => { all = d; list(); }, { emptyMsg: 'No warnings. All clear.', label: 'Loading warnings' });
  }
  detail(id);
  function list() {
    const el = $('#wlist', root), rows = all.filter(w => (fSev === 'all' || w.severity === fSev) && (fStat === 'all' || w.status === fStat));
    el.innerHTML = rows.length ? rows.map((w, i) => `<a class="wcard ${w.id === id ? 'sel' : ''}" href="#/warnings/${w.id}" style="--i:${i}">
      <span class="sev" style="background:${SEV[w.severity]}"></span>
      <div class="wmain"><div class="wt">${esc(w.countryName)} <span>needs</span> ${esc(w.requirement.toLowerCase())}</div><div class="ws">${esc(w.study)} · ${w.shipmentsAffected} shipments · ${esc(w.severity)}</div></div>
      <div class="wr"><span class="badge s-${w.status}">${w.status.replace('_', ' ')}</span><time>${ago(w.createdAt)}</time></div></a>`).join('') : '<div class="state">No warnings match these filters.</div>';
  }
  async function detail(wid) {
    $$('.wcard', root).forEach(c => c.classList.toggle('sel', c.getAttribute('href') === '#/warnings/' + wid));
    const el = $('#wdetail', root); root.classList.toggle('has-detail', !!wid);
    if (!wid) { el.innerHTML = '<div class="state">Select a warning to see details.</div>'; return; }
    el.innerHTML = loading('Loading warning');
    try { const w = await getWarning(wid);
      el.innerHTML = `<div class="k" style="color:${SEV[w.severity]}">${esc(w.severity)} · ${ago(w.createdAt)}</div><h3>${esc(w.countryName)} needs <em>${esc(w.requirement.toLowerCase())}.</em></h3>
      <p class="l">${esc(w.summary)}</p><dl><dt>Study</dt><dd>${esc(w.study)}</dd><dt>Shipments affected</dt><dd>${w.shipmentsAffected}</dd><dt>Status</dt><dd>${w.status.replace('_', ' ')}</dd><dt>Recommended</dt><dd>${esc(w.recommendedAction)}</dd><dt>Source</dt><dd>${esc(w.source)}</dd><dt>Linked shipments</dt><dd>${w.shipmentIds.map(s => `<span class="lchip">${s}</span>`).join(' ') || '—'}</dd>${w.kind === 'fire' ? fireRows(w) : ''}</dl>
      <a class="btn" href="${w.kind === 'fire' ? '#/max/max-alerts' : '#/max'}">Discuss with Max →</a> <a class="btn ghost" href="#/warnings">Close</a>`;
    } catch (e) { el.innerHTML = errorState(e, 'wretry'); $('#wretry').onclick = () => detail(wid); }
  }
}

const etf = iso => iso ? new Date(iso).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' ET' : '—';
// Extra rows for NASA FIRMS route warnings (same dl layout as other warnings).
function fireRows(w) {
  const f = w.fire;
  return `<dt>Disaster</dt><dd>Wildfire · satellite heat detection (NASA FIRMS)</dd><dt>Location</dt><dd>${esc(f.place || '—')}</dd><dt>Coordinates</dt><dd>${f.lat.toFixed(4)}, ${f.lng.toFixed(4)}</dd>
  <dt>Distance from route</dt><dd>${f.distanceKm.toFixed(1)} km</dd><dt>Affected segment</dt><dd>${esc(f.segment)} (km ${f.segmentKm.map(Math.round).join('–')})</dd>
  <dt>Observed</dt><dd>${etf(f.observedAt)} · ${esc(f.confidence)} confidence${f.maxFrpMW != null ? ` · ${f.maxFrpMW} MW FRP` : ''} · ${f.detections} detection(s)${f.satellites?.length ? ` · ${esc(f.satellites.join(', '))}` : ''}</dd>
  <dt>Risk</dt><dd>${esc(w.risk)} · ${w.confirmation === 'confirmed' ? 'confirmed' : 'potential, not confirmed (no road-closure data)'}</dd>
  <dt>Delivery impact</dt><dd>${esc(w.impact)}${f.alternative?.reason ? ` ${esc(f.alternative.reason)}` : ''}</dd>
  <dt>ETA</dt><dd>${f.revisedEta ? `${etf(w.eta)} → ${etf(f.revisedEta)} if rerouted` : `${etf(w.eta)} · delay unconfirmed`}</dd>
  <dt>Photon</dt><dd>${(w.notifications || []).map(n => `${esc(n.status)} · ${esc(n.recipient)}${n.reason ? ` · ${esc(n.reason)}` : ''}`).join('<br>') || '—'}</dd>`;
}
