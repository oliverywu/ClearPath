import { USE_MOCK, API_BASE, MOCK_LATENCY_MS } from './config.js';
const q = new URLSearchParams(location.search);
const sleep = () => new Promise(r => setTimeout(r, MOCK_LATENCY_MS[0] + Math.random() * (MOCK_LATENCY_MS[1] - MOCK_LATENCY_MS[0])));
const cache = {};
async function mock(file) {
  await sleep();
  if (q.has('fail')) throw new Error('Simulated network error');
  if (!cache[file]) { const r = await fetch(new URL(`./mock/${file}.json`, import.meta.url)); if (!r.ok) throw new Error(`Mock ${file} ${r.status}`); cache[file] = await r.json(); }
  const d = cache[file];
  return q.has('empty') && Array.isArray(d) ? [] : d;
}
async function http(path, opts = {}) {
  const r = await fetch(API_BASE + path, { headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, ...opts });
  if (!r.ok) { let detail = ''; try { detail = (await r.json()).error || ''; } catch {} throw new Error(detail || `${opts.method || 'GET'} ${path} → ${r.status}`); }
  return r.status === 204 ? null : r.json();
}
/** GET /api/warnings  → Warning[] (newest first) */
export async function getWarnings() {
  if (!USE_MOCK) return http('/warnings');
  return (await mock('warnings')).slice().sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}
/** GET /api/warnings/:id → Warning */
export async function getWarning(id) {
  if (!USE_MOCK) return http(`/warnings/${encodeURIComponent(id)}`);
  const w = (await mock('warnings')).find(x => x.id === id); if (!w) throw new Error(`Warning ${id} not found`); return w;
}
/** GET /api/shipments → Shipment[] */
export async function getShipments() { return USE_MOCK ? mock('shipments') : http('/shipments'); }
/** GET /api/inventory → { configured, items: InventoryItem[], message, provenance }
 *  The integrated backend has no inventory source, so it returns configured:false with an
 *  explanation instead of passing shipment schedules off as stock. */
export async function getInventoryStatus() {
  if (USE_MOCK) return { configured: true, items: await mock('inventory'), message: '', provenance: 'sample' };
  return http('/inventory');
}
export async function getInventory() { return (await getInventoryStatus()).items; }
/** GET /api/context → { today, trial, currentPlan, providers } (planning date and current-plan state) */
export async function getContext() {
  if (USE_MOCK) return { today: '2026-10-17', trial: { study: 'NOVA-24' }, currentPlan: null, providers: {}, mock: true };
  return http('/context');
}
/** GET /api/photon/chats → Chat[] */
export async function getPhotonChats() {
  if (!USE_MOCK) return http('/photon/chats');
  return (await mock('chats')).slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}
/** GET /api/photon/chats/:id/messages → Message[] (oldest first) */
export async function getChatMessages(chatId) {
  if (!USE_MOCK) return http(`/photon/chats/${encodeURIComponent(chatId)}/messages`);
  const all = await mock('messages'); return all[chatId] || [];
}
/** POST /api/photon/chats/:id/messages  body {text} → { message: Message, replies: Message[] }
 *  `replies` are Max's responses (may be empty if Max answers later; then poll getChatMessages). */
export async function sendChatMessage(chatId, text, clientMessageId = newMessageId()) {
  // clientMessageId lets the backend dedupe a resend of the same message (no duplicate decisions).
  if (!USE_MOCK) return http(`/photon/chats/${encodeURIComponent(chatId)}/messages`, { method: 'POST', body: JSON.stringify({ text, clientMessageId }) });
  await sleep(); if (q.has('fail')) throw new Error('Simulated send error');
  const all = cache.messages || (cache.messages = await (await fetch(new URL('./mock/messages.json', import.meta.url))).json());
  const list = (all[chatId] ||= []);
  const message = { id: `${chatId}-m${Date.now()}`, from: 'me', text, sentAt: new Date().toISOString() };
  list.push(message);
  const replies = scriptedReply(chatId, text).map((r, i) => ({ id: `${chatId}-r${Date.now()}${i}`, from: 'max', sentAt: new Date().toISOString(), caption: 'Synthetic demo reply', ...r }));
  list.push(...replies);
  return { message, replies };
}
function newMessageId() { return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
// Mock-only scripted replies for isolated frontend development. Never used with the real backend.
function scriptedReply(chatId, text) {
  const t = text.trim().toUpperCase();
  const fixes = { '1': 'Relabel in Boston before departure (+2 days)', '2': 'Relabel at the Tokyo depot (+9 days)', '3': 'Split shipment: 12 kits now, 11 after relabel' };
  if (fixes[t]) return [{ text: `Got it, option ${t}: ${fixes[t]}.` }, { card: { type: 'plan', title: 'Japan, updated plan', rows: [['Safe ship-by', t === '2' ? 'Nov 18' : 'Nov 11'], ['Likely ship-by', t === '2' ? 'Nov 21' : 'Nov 12'], ['Status', 'Needs approval']], tone: 'ok' }, links: [{ label: 'View the plan', href: '#/' }], quickReplies: ['APPROVE', 'Not yet'] }];
  if (t === 'APPROVE') return [{ text: 'Approved and logged to the audit history. I’ll tell the Tokyo depot.' }];
  if (t === 'REJECT') return [{ text: 'Rejected. I’ll keep the current plan and flag it for tomorrow’s review.' }];
  if (/REROUTE/.test(t)) return [{ text: 'Drafted scenario S-115: reroute ORX-2 via Singapore, +5 days. Sent to Lars for review.' }];
  return [{ text: 'Noted. I’ll factor that into the plan and get back to you.' }];
}
/** GET /api/calendar?month=YYYY-MM → { month, events: CalendarEvent[] } */
export async function getCalendar(month) {
  if (!USE_MOCK) return http(`/calendar?month=${encodeURIComponent(month)}`);
  const all = await mock('calendar'); return all.find(m => m.month === month) || { month, events: [] };
}
/** GET /api/schedule/:date → DaySchedule { date, items: TimelineItem[] } */
export async function getDaySchedule(date) {
  if (!USE_MOCK) return http(`/schedule/${encodeURIComponent(date)}`);
  const all = await mock('day-schedules'); return { date, items: all[date]?.items || [] };
}
/** GET /api/chalk/insights?date=YYYY-MM-DD → ChalkInsight { date, risk, summary, recommendations[] }
 *  Chalk AI integration point: the backend calls Chalk AI and returns this shape. */
export async function getChalkInsight(date) {
  if (!USE_MOCK) return http(`/chalk/insights?date=${encodeURIComponent(date)}`);
  const all = await mock('day-schedules'); const i = all[date]?.insight;
  return i ? { date, ...i } : { date, risk: 'low', summary: 'No shipment milestones on this day.', recommendations: [] };
}
/** GET /api/tracking → TrackingSummary[] (one per active shipment; joins shipments by id) */
export async function getTracking() {
  if (!USE_MOCK) return http('/tracking');
  const [ships, trk] = await Promise.all([mock('shipments'), mock('tracking')]);
  return trk.map(t => ({ ...ships.find(s => s.id === t.id), ...t }));
}
/** GET /api/tracking/:id → TrackingDetail (TrackingSummary incl. milestones) */
export async function getTrackingDetail(id) {
  if (!USE_MOCK) return http(`/tracking/${encodeURIComponent(id)}`);
  const t = (await getTracking()).find(x => x.id === id); if (!t) throw new Error(`Tracking ${id} not found`); return t;
}
/** Governance reads (real backend only; mock mode has no planner). */
export const getProposal = id => http(`/proposals/${encodeURIComponent(id)}`);
export const getProposalComparison = id => http(`/proposals/${encodeURIComponent(id)}/comparison`);
export const getCurrentPlan = () => USE_MOCK ? Promise.resolve(null) : http('/current-plan');
export const getAuditHistory = (entityIds = []) => USE_MOCK ? Promise.resolve([]) : http(`/audit-history?entityId=${encodeURIComponent(entityIds.join(','))}`);
export const getEvidence = warningId => USE_MOCK ? Promise.resolve([]) : http(`/evidence?warningId=${encodeURIComponent(warningId)}`);
// "Max" aliases (Max is the assistant behind the Photon messaging integration)
export const getMaxChats = getPhotonChats;
export const getMaxMessages = getChatMessages;
export const sendMaxMessage = sendChatMessage;

export async function analyzeShipmentRoute({ origin, destination, proximityKm }) {
  return http('/route-analysis', { method: 'POST', body: JSON.stringify({ origin, destination, proximityKm }) });
}
