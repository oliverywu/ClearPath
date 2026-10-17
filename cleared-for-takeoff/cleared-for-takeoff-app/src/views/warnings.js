import { $, $$, esc, SEV, ago, fmtDate, load, loading, errorState } from '../ui.js';
import { getWarnings, getWarning } from '../api.js';
let all = [], fSev = 'all', fStat = 'all';
const EVID = { synthetic: 'Synthetic', needs_review: 'Needs review', verified: 'Verified', retired: 'Retired' };
const PLAN = { proposed: 'Proposed', approved: 'Approved · current', rejected: 'Rejected', superseded: 'Superseded' };
const AUDIT = { 'current_plan.changed': 'Current plan changed', 'proposal.created': 'Proposals calculated', 'proposal.rejected': 'Proposal rejected',
  'proposal.approve_refused': 'Approval refused', 'proposal.reject_refused': 'Rejection refused', 'scenario.approved': 'Decision recorded',
  'scenario.rejected': 'Decision recorded', 'change_event.ingested': 'Disruption ingested', 'evidence.reviewed': 'Evidence reviewed', 'scenario.generated': 'Scenario calculated' };
export async function renderWarnings(root, id, entered = true) {
  if (!root.dataset.ready) {
    root.dataset.ready = 1;
    root.innerHTML = `<div class="vhead"><a class="back" href="#/">← Landing</a><div class="k">Cleared for Takeoff · warnings</div><h2>All recent <em>warnings.</em></h2>
    <div class="invbar" id="wfilt">${['all', 'critical', 'high', 'medium', 'low'].map(s => `<button class="chip ${s === 'all' ? 'on' : ''}" data-sev="${s}">${s === 'all' ? 'Any severity' : s}</button>`).join('')}<span class="sep"></span>
    ${[['all', 'Any status'], ['open', 'Open'], ['in_review', 'In review'], ['resolved', 'Resolved']].map(([k, l]) => `<button class="chip ${k === 'all' ? 'on' : ''}" data-ws="${k}">${l}</button>`).join('')}</div></div>
    <div class="wlay"><div id="wlist" class="wlist"></div><aside id="wdetail" class="wdetail"></aside></div>`;
    $$('#wfilt .chip', root).forEach(c => c.onclick = () => { const g = c.dataset.sev ? 'sev' : 'ws'; $$(`#wfilt [data-${g}]`, root).forEach(x => x.classList.toggle('on', x === c)); if (g === 'sev') fSev = c.dataset.sev; else fStat = c.dataset.ws; list(); });
  }
  // Reload when the view is (re)entered: approvals made in Max change warning status and the current plan.
  if (entered) await load($('#wlist', root), getWarnings, d => { all = d; list(); }, { emptyMsg: 'No warnings. All clear.', label: 'Loading warnings' });
  detail(id);
  function list() {
    const el = $('#wlist', root), rows = all.filter(w => (fSev === 'all' || w.severity === fSev) && (fStat === 'all' || w.status === fStat));
    el.innerHTML = rows.length ? rows.map((w, i) => `<a class="wcard ${w.id === id ? 'sel' : ''}" href="#/warnings/${w.id}" style="--i:${i}">
      <span class="sev" style="background:${SEV[w.severity]}"></span>
      <div class="wmain"><div class="wt">${esc(w.countryName)} <span>·</span> ${esc(w.requirement)}</div><div class="ws">${esc(w.study)} · ${w.shipmentsAffected} shipment${w.shipmentsAffected === 1 ? '' : 's'} · ${esc(w.severity)}${w.provenance && w.provenance !== 'live' ? ` · ${esc(w.provenance.replace('_', ' '))}` : ''}</div></div>
      <div class="wr"><span class="badge s-${w.status}">${w.status.replace('_', ' ')}</span><time>${ago(w.createdAt)}</time></div></a>`).join('') : '<div class="state">No warnings match these filters.</div>';
  }
  async function detail(wid) {
    $$('.wcard', root).forEach(c => c.classList.toggle('sel', c.getAttribute('href') === '#/warnings/' + wid));
    const el = $('#wdetail', root); root.classList.toggle('has-detail', !!wid);
    if (!wid) { el.innerHTML = '<div class="state">Select a warning to see details.</div>'; return; }
    el.innerHTML = loading('Loading warning');
    try { const w = await getWarning(wid);
      el.innerHTML = `<div class="k" style="color:${SEV[w.severity]}">${esc(w.severity)} · ${ago(w.createdAt)}</div><h3>${esc(w.countryName)}: <em>${esc(w.requirement)}.</em></h3>
      <p class="l">${esc(w.summary)}</p><dl><dt>Study</dt><dd>${esc(w.study)}</dd><dt>Shipments affected</dt><dd>${w.shipmentsAffected}</dd><dt>Status</dt><dd>${w.status.replace('_', ' ')}</dd><dt>Recommended</dt><dd>${esc(w.recommendedAction)}</dd><dt>Source</dt><dd>${esc(w.source)}${w.evidenceStatus ? ` <span class="ev-chip ev-${w.evidenceStatus}">${EVID[w.evidenceStatus]}</span>` : ''}</dd><dt>Linked shipments</dt><dd>${w.shipmentIds.slice(0, 8).map(s => `<span class="lchip">${esc(s)}</span>`).join(' ') || '—'}${w.shipmentIds.length > 8 ? ` <small>+${w.shipmentIds.length - 8} more</small>` : ''}</dd>
      ${w.currentPlan ? `<dt>Current plan</dt><dd>v${w.currentPlan.version} · ${esc(w.currentPlan.planId)}${w.currentPlan.approvedBy ? ` · approved by ${esc(w.currentPlan.approvedBy)}` : ''}</dd>` : ''}</dl>
      ${options(w)}${evidence(w)}${audit(w)}
      <a class="btn" href="#/max">Discuss with Max →</a> <a class="btn ghost" href="#/warnings">Close</a>`;
    } catch (e) { el.innerHTML = errorState(e, 'wretry'); $('#wretry').onclick = () => detail(wid); }
  }
}
function options(w) {
  if (!w.options) return '';
  if (!w.options.length) return '<div class="wsec"><div class="k">Remediation options</div><div class="state">No proposals calculated for this warning.</div></div>';
  return `<div class="wsec"><div class="k">Remediation options · approve in Max</div>${w.options.map(o => { const p = o.preview[0];
    return `<div class="wopt ${o.status}"><div class="wopt-h"><b>${o.number}. ${esc(o.title)}</b><span class="badge p-${o.status}">${PLAN[o.status] || esc(o.status)}</span>${o.recommended && o.status === 'proposed' ? '<span class="badge p-rec">Recommended</span>' : ''}</div>
      ${p ? `<div class="wopt-r">${esc(p.countryName)}: ${fmtDate(p.before.projectedDelivery)} → <b>${fmtDate(p.after.projectedDelivery)}</b> · slack ${p.before.slackDays} → <b>${p.after.slackDays}</b> business days · ${esc(p.after.status.replace('_', ' '))} · safe ship-by ${fmtDate(p.after.shipBy?.safe)}</div>` : ''}
      <div class="wopt-m">${o.preview.length > 1 ? `${o.preview.length} shipments change · ` : ''}cost proxy ${o.costDelta >= 0 ? '+' : ''}${o.costDelta} · proposal ${esc(o.proposalId)}</div></div>`; }).join('')}</div>`;
}
function evidence(w) {
  if (!w.evidence) return '';
  return `<div class="wsec"><div class="k">Evidence &amp; citations</div>${w.evidence.map(e => `<div class="wev"><span class="ev-chip ev-${e.status}">${EVID[e.status] || esc(e.status)}</span> <b>${esc(e.title)}</b>${e.requirementKey ? ` <small>${esc(e.requirementKey)}</small>` : ''}
    ${e.excerpt ? `<p>“${esc(e.excerpt)}”</p>` : ''}${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.url)}</a>` : '<small>No source link recorded</small>'}</div>`).join('')}</div>`;
}
function audit(w) {
  if (!w.audit) return '';
  const rows = w.audit.filter(a => a.action !== 'scenario.generated').slice(0, 12);
  return `<div class="wsec"><div class="k">Audit history</div>${rows.length ? `<ol class="waud">${rows.map(a => `<li><time>${ago(a.createdAt)}</time><span>${esc(AUDIT[a.action] || a.action)}</span><small>${esc(a.actor)}${a.payload?.channel ? ' · ' + esc(a.payload.channel) : ''}${a.payload?.version ? ' · v' + a.payload.version : ''}${a.payload?.reason ? ' · ' + esc(a.payload.reason) : ''}</small></li>`).join('')}</ol>` : '<div class="state">No decisions recorded yet.</div>'}</div>`;
}
