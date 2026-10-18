import { $, $$, esc, loading, errorState } from '../ui.js';
import { getRegulatoryEvidence } from '../api.js';

let records = [], country = 'all', status = 'official', query = '', selected = '';
const NAMES = typeof Intl.DisplayNames === 'function' ? new Intl.DisplayNames(['en'], { type: 'region' }) : null;
const STATUS = { verified: 'Verified', needs_review: 'Needs review', synthetic: 'Planning assumption', retired: 'Retired' };

const countryName = code => { try { return NAMES?.of(code) || code; } catch { return code || 'Global'; } };
const flag = code => /^[A-Z]{2}$/.test(code || '') ? String.fromCodePoint(...code.split('').map(c => 127397 + c.charCodeAt(0))) : '◎';
const sourceHost = url => { try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return 'No link recorded'; } };
const safeUrl = url => { try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) ? u.href : '#'; } catch { return '#'; } };
const fullDate = value => value ? new Date(value.length === 10 ? value + 'T12:00:00' : value).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : 'Not recorded';
const pretty = value => String(value || '').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
function ruleValue(value) {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'object') return Object.entries(value).map(([k, v]) => `${pretty(k)}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ');
  return String(value);
}

export async function renderSources(root, entered = true) {
  if (!root.dataset.ready) {
    root.dataset.ready = 1;
    root.innerHTML = `<div class="vhead source-head"><a class="back" href="#/">← Landing</a><div class="k">Cleared for Takeoff · regulatory intelligence</div><h2>Laws, rules &amp; <em>sources.</em></h2><p class="l">The evidence layer behind country planning—kept distinct from simulated operational events.</p></div><div id="source-body">${loading('Loading regulatory evidence')}</div>`;
  }
  if (!entered && records.length) { draw(root); return; }
  const body = $('#source-body', root); body.innerHTML = loading('Loading regulatory evidence');
  try { records = (await getRegulatoryEvidence()).filter(r => r.kind !== 'event'); draw(root); }
  catch (e) { body.innerHTML = errorState(e, 'source-retry'); $('#source-retry', root).onclick = () => renderSources(root, true); }
}

function draw(root) {
  const body = $('#source-body', root);
  const countries = [...new Set(records.map(r => r.jurisdiction).filter(Boolean))].sort((a, b) => countryName(a).localeCompare(countryName(b)));
  const official = records.filter(r => r.sourceTier === 'official');
  const verified = official.filter(r => r.status === 'verified');
  const modeled = records.filter(r => r.sourceTier === 'modeled' || r.sourceTier === 'synthetic' || r.status === 'synthetic');
  const needle = query.trim().toLowerCase();
  const rows = records.filter(r => country === 'all' || r.jurisdiction === country)
    .filter(r => status === 'all' || (status === 'official' && r.sourceTier === 'official') || (status === 'verified' && r.sourceTier === 'official' && r.status === 'verified') || (status === 'review' && r.status === 'needs_review') || (status === 'modeled' && (r.sourceTier === 'modeled' || r.sourceTier === 'synthetic' || r.status === 'synthetic')))
    .filter(r => !needle || JSON.stringify(r).toLowerCase().includes(needle) || countryName(r.jurisdiction).toLowerCase().includes(needle))
    .sort((a, b) => countryName(a.jurisdiction).localeCompare(countryName(b.jurisdiction)) || String(a.requirementKey).localeCompare(String(b.requirementKey)));
  if (!rows.some(r => r.id === selected)) selected = rows[0]?.id || '';
  const active = rows.find(r => r.id === selected);
  body.innerHTML = `<div class="source-stats"><div><b>${countries.length}</b><span>jurisdictions</span></div><div><b>${official.length}</b><span>official rules</span></div><div><b>${verified.length}</b><span>verified official</span></div><div><b>${modeled.length}</b><span>planning assumptions</span></div></div>
  <div class="source-note"><b>Verified law ≠ live event.</b> A verified badge here means the rule has cited evidence and completed review. A synthetic warning means only that the disruption is a test scenario.</div>
  <div class="source-tools"><label><span>Search</span><input id="source-search" value="${esc(query)}" placeholder="Labels, permits, languages, authorities…"></label><label><span>Country</span><select id="source-country"><option value="all">All jurisdictions (${countries.length})</option>${countries.map(c => `<option value="${esc(c)}" ${country === c ? 'selected' : ''}>${flag(c)} ${esc(countryName(c))}</option>`).join('')}</select></label><label><span>Evidence</span><select id="source-status"><option value="official" ${status === 'official' ? 'selected' : ''}>Official sources (${official.length})</option><option value="verified" ${status === 'verified' ? 'selected' : ''}>Verified official (${verified.length})</option><option value="review" ${status === 'review' ? 'selected' : ''}>Needs review</option><option value="modeled" ${status === 'modeled' ? 'selected' : ''}>Planning assumptions (${modeled.length})</option><option value="all" ${status === 'all' ? 'selected' : ''}>All records (${records.length})</option></select></label></div>
  <div class="source-layout"><div class="source-list"><div class="source-list-head"><div><div class="k">Regulatory database</div><b>${rows.length} matching ${rows.length === 1 ? 'record' : 'records'}</b></div><span>Select a record for its evidence</span></div>${rows.length ? rows.map((r, i) => card(r, i)).join('') : '<div class="state">No evidence matches these filters.</div>'}</div><aside class="source-detail">${detail(active)}</aside></div>
  <p class="source-disclaimer">Official rules are cited regulatory evidence. Modeled records are transparent planning assumptions used for calculations. This prototype does not replace protocol-specific legal or regulatory review.</p>`;
  $('#source-search', root).oninput = e => { query = e.target.value; draw(root); };
  $('#source-country', root).onchange = e => { country = e.target.value; selected = ''; draw(root); };
  $('#source-status', root).onchange = e => { status = e.target.value; selected = ''; draw(root); };
  $$('.source-card', root).forEach(el => el.onclick = () => { selected = el.dataset.id; draw(root); });
}

function card(r, i) {
  return `<button class="source-card ${r.id === selected ? 'sel' : ''}" data-id="${esc(r.id)}" style="--i:${i}"><span class="source-flag">${flag(r.jurisdiction)}</span><span class="source-card-main"><b>${esc(r.requirementKey || r.title || 'Requirement')}</b><small>${esc(countryName(r.jurisdiction))} · ${esc(pretty(r.ruleType || 'regulatory'))}</small></span><span class="source-card-value">${esc(ruleValue(r.value))}</span><span class="ev-chip ev-${esc(r.status)}">${esc(STATUS[r.status] || pretty(r.status))}</span></button>`;
}

function detail(r) {
  if (!r) return '<div class="source-detail-empty"><b>Select a regulatory record</b><span>Its exact excerpt, dates, review status, and primary link will appear here.</span></div>';
  return `<div class="k">Source evidence</div><h3>${esc(r.requirementKey || r.title || 'Requirement')}</h3><div class="source-country-title"><span>${flag(r.jurisdiction)}</span><div><b>${esc(countryName(r.jurisdiction))}</b><small>${esc(pretty(r.ruleType || 'regulatory rule'))}</small></div></div><div class="source-badges"><span class="ev-chip ev-${esc(r.status)}">${esc(STATUS[r.status] || pretty(r.status))}</span><span class="ev-chip ev-${esc(r.sourceTier)}">${esc(pretty(r.sourceTier))}</span></div><dl><dt>Requirement</dt><dd>${esc(ruleValue(r.value))}</dd><dt>Effective</dt><dd>${fullDate(r.effectiveFrom)}${r.effectiveTo ? ` — ${fullDate(r.effectiveTo)}` : ' onward'}</dd><dt>Last verified</dt><dd>${esc(r.lastVerifiedAt || r.retrievedAt || 'Not recorded')}</dd>${r.confidence !== null && r.confidence !== undefined ? `<dt>Confidence</dt><dd>${Math.round(Number(r.confidence) * 100)}%</dd>` : ''}</dl><div class="source-excerpt"><span>Exact cited excerpt</span><p>“${esc(r.excerpt || 'No excerpt is recorded for this requirement.')}”</p></div><div class="source-doc"><span>Source document</span><b>${esc(r.title || 'Untitled source')}</b><small>${esc(sourceHost(r.url))}</small>${r.url ? `<a class="btn" href="${esc(safeUrl(r.url))}" target="_blank" rel="noopener noreferrer">Open official source ↗</a>` : ''}</div>${r.notes ? `<div class="source-notes"><span>Notes</span><p>${esc(r.notes)}</p></div>` : ''}`;
}
