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
  if (!r.ok) throw new Error(`${opts.method || 'GET'} ${path} → ${r.status}`);
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
/** GET /api/inventory → InventoryItem[] (recurring shipments) */
export async function getInventory() { return USE_MOCK ? mock('inventory') : http('/inventory'); }
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
/** POST /api/photon/chats/:id/messages  body {text} → Message */
export async function sendChatMessage(chatId, text) {
  if (!USE_MOCK) return http(`/photon/chats/${encodeURIComponent(chatId)}/messages`, { method: 'POST', body: JSON.stringify({ text }) });
  await sleep(); if (q.has('fail')) throw new Error('Simulated send error');
  const all = cache.messages || (cache.messages = await (await fetch(new URL('./mock/messages.json', import.meta.url))).json());
  const m = { id: `${chatId}-m${Date.now()}`, from: 'me', text, sentAt: new Date().toLocaleTimeString('en-GB').slice(0, 5) };
  (all[chatId] ||= []).push(m); return m;
}
