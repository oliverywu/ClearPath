import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseFirmsCsv, getFires, clearFirmsCache, normalizeConfidence } from '../lib/firms.js';
import { analyzeFires, compareAlternatives } from '../lib/fire-analysis.js';
import { estimatePosition } from '../lib/tracking.js';
import { cumulativeKm } from '../lib/geo.js';
import { FireMonitor } from '../lib/monitor.js';
import { IntelStore } from '../lib/store.js';
import { sendPhotonText } from '../lib/photon.js';

const NOW = Date.parse('2026-10-17T20:00:00Z');
// Straight north-south route along -75.64 from 40.5 to 43.5 (~333 km).
const ROUTE = Array.from({ length: 31 }, (_, i) => ({ lat: 40.5 + i * 0.1, lng: -75.64 }));
const DETOUR = [{ lat: 40.5, lng: -75.64 }, { lat: 41.0, lng: -76.4 }, { lat: 42.0, lng: -76.4 }, { lat: 43.5, lng: -75.64 }];
const CSV = readFileSync(new URL('./fixtures/firms-route.csv', import.meta.url), 'utf8');
const FIRES = parseFirmsCsv(CSV, 'VIIRS_SNPP_NRT');
const ship = (over = {}) => ({ id: 'RX-1042', origin: 'A', destination: 'B', departedAt: '2026-10-17T18:00:00Z', eta: '2026-10-18T00:00:00Z', stops: [{ name: 'Start', lat: 40.5, lng: -75.64 }, { name: 'Mid', lat: 42, lng: -75.64 }, { name: 'End', lat: 43.5, lng: -75.64 }], contacts: [{ id: 'r', name: 'Recipient', role: 'recipient', photonSpaceId: 'pho_spc_00000000000000000000000001' }], ...over });
const PHOTON_ENV = { PHOTON_API_KEY: 'pho_sk_test', PHOTON_PROJECT_ID: 'pho_prj_00000000000000000000000001', PHOTON_SENDER_ID: 'pho_usr_00000000000000000000000001' };
function monitorWith({ fires = FIRES, status = 'ok', shipment = ship(), env = PHOTON_ENV, fetchImpl, routes = [{ points: ROUTE, distanceMeters: 333000, durationSec: 4 * 3600 }, { points: DETOUR, distanceMeters: 380000, durationSec: 4.5 * 3600 }] } = {}) {
  const calls = { photon: 0, alt: 0 };
  const m = new FireMonitor({ shipments: [shipment], store: new IntelStore(), env, now: () => NOW,
    computeRoutes: async ({ alternatives }) => { if (alternatives) { calls.alt++; return routes; } return [routes[0]]; },
    getFiresImpl: async () => ({ status, fires, fetchedAt: new Date(NOW).toISOString(), newestObservation: fires[0]?.observedAt || null, errors: [], sources: ['VIIRS_SNPP_NRT'], days: 2, message: status === 'ok' ? null : status }),
    fetchImpl: fetchImpl || (async () => { calls.photon++; return new Response(JSON.stringify({ id: 'pho_msg_00000000000000000000000009', status: 'dispatched' }), { status: 202 }); }) });
  return { m, calls };
}

test('parses FIRMS CSV with confidence, FRP, satellite and UTC time', () => {
  assert.equal(FIRES.length, 3);
  assert.equal(FIRES[0].confidence, 'high'); assert.equal(FIRES[0].frpMW, 62.3); assert.equal(FIRES[0].satellite, 'N');
  assert.equal(FIRES[0].observedAt, '2026-10-17T17:12:00.000Z');
  assert.equal(normalizeConfidence('85'), 'high'); assert.equal(normalizeConfidence('10'), 'low');
  assert.throws(() => parseFirmsCsv('Invalid MAP_KEY.'), /unexpected response/);
});

test('fire near the route is matched with distance, segment and high risk', () => {
  const r = analyzeFires({ points: ROUTE, fires: FIRES, corridorKm: 25, stops: ship().stops.map(s => ({ ...s, alongKm: (s.lat - 40.5) * 111.2 })), now: NOW });
  assert.equal(r.fires.length, 2); assert.equal(r.ignoredFar, 1);
  const e = r.events[0];
  assert.equal(e.risk, 'high'); assert.ok(e.distanceKm < 1); assert.equal(e.detections, 2);
  assert.equal(e.segment.label, 'between Start and Mid'); assert.equal(e.confirmed, false);
});

test('far-away fire is ignored', () => {
  const r = analyzeFires({ points: ROUTE, fires: [FIRES[2]], corridorKm: 25, now: NOW });
  assert.equal(r.fires.length, 0); assert.equal(r.events.length, 0); assert.equal(r.ignoredFar, 1);
});

test('shipment with no detections: no warnings, no notifications', async () => {
  const { m, calls } = monitorWith({ fires: [], status: 'empty' });
  const out = await m.run('RX-1042');
  assert.equal(out.warnings.length, 0); assert.equal(out.firms.status, 'empty'); assert.equal(calls.photon, 0);
});

test('missing FIRMS key reports no_key without calling NASA', async () => {
  let called = false;
  const r = await getFires([-80, 40, -74, 44], { key: '', fetchImpl: async () => { called = true; } });
  assert.equal(r.status, 'no_key'); assert.equal(called, false); assert.match(r.message, /FIRMS_MAP_KEY/);
});

test('outdated FIRMS data is flagged stale and never raises warnings', async () => {
  clearFirmsCache();
  const old = CSV.replaceAll('2026-10-17', '2026-10-10');
  const r = await getFires([-80, 40, -74, 44], { key: 'k', sources: ['VIIRS_SNPP_NRT'], now: NOW, fetchImpl: async () => new Response(old) });
  assert.equal(r.status, 'stale');
  const { m, calls } = monitorWith({ fires: r.fires, status: 'stale' });
  const out = await m.run('RX-1042');
  assert.equal(out.warnings.length, 0); assert.equal(calls.photon, 0);
  const a = analyzeFires({ points: ROUTE, fires: r.fires, now: NOW });
  assert.ok(a.events.every(e => e.outdated && e.risk === 'low'));
});

test('FIRMS network failure surfaces an error state and hides the key', async () => {
  clearFirmsCache();
  const r = await getFires([-80, 40, -74, 44], { key: 'SECRETKEY', sources: ['MODIS_NRT'], fetchImpl: async () => { throw new Error('boom SECRETKEY'); } });
  assert.equal(r.status, 'error'); assert.ok(!JSON.stringify(r).includes('SECRETKEY'));
});

test('no GPS: position is labeled estimated and interpolated from departure/ETA', () => {
  const cum = cumulativeKm(ROUTE);
  const t = estimatePosition({ shipment: ship(), points: ROUTE, cum, durationSec: 6 * 3600, now: NOW });
  assert.equal(t.mode, 'estimated'); assert.equal(t.label, 'Estimated position'); assert.equal(t.isLive, false);
  assert.ok(Math.abs(t.progress - 1 / 3) < 0.01);
  assert.deepEqual(t.stops.map(s => s.state), ['completed', 'upcoming', 'upcoming']);
  const stale = estimatePosition({ shipment: ship({ gps: { lat: 42, lng: -75.64, at: '2026-10-17T10:00:00Z' } }), points: ROUTE, cum, durationSec: 6 * 3600, now: NOW });
  assert.equal(stale.mode, 'estimated');
  const live = estimatePosition({ shipment: ship({ gps: { lat: 42, lng: -75.64, at: '2026-10-17T19:50:00Z' } }), points: ROUTE, cum, durationSec: 6 * 3600, now: NOW });
  assert.equal(live.mode, 'gps'); assert.equal(live.stops[1].state, 'current');
  const demo = estimatePosition({ shipment: ship(), points: ROUTE, cum, durationSec: 6 * 3600, now: NOW, demo: true });
  assert.equal(demo.mode, 'demo'); assert.match(demo.label, /simulated/);
});

test('alternative route that avoids the fire yields a revised ETA', () => {
  const a = analyzeFires({ points: ROUTE, fires: FIRES, now: NOW });
  const c = compareAlternatives({ routes: [{ points: ROUTE, durationSec: 14400 }, { points: DETOUR, durationSec: 16200, distanceMeters: 1 }], event: a.events[0], fires: a.fires, etaIso: '2026-10-18T00:00:00Z' });
  assert.equal(c.available, true); assert.equal(c.delayMinutes, 30); assert.equal(c.revisedEta, '2026-10-18T00:30:00.000Z');
  const none = compareAlternatives({ routes: [{ points: ROUTE, durationSec: 14400 }], event: a.events[0], fires: a.fires, etaIso: '2026-10-18T00:00:00Z' });
  assert.equal(none.available, false); assert.equal(none.revisedEta, null);
});

test('end to end: warning created, Photon submitted once, duplicates suppressed, resolved later', async () => {
  const { m, calls } = monitorWith();
  const a = await m.run('RX-1042');
  assert.equal(a.warnings.length, 1);
  const w = a.warnings[0];
  assert.equal(w.confirmation, 'potential'); assert.equal(w.risk, 'high'); assert.equal(w.fire.delayMinutes, 30); assert.ok(w.fire.revisedEta);
  assert.equal(w.notifications[0].status, 'submitted'); assert.equal(calls.photon, 1);
  assert.match(m.store.notifications[0].text, /Shipment RX-1042 may experience a delay due to a fire-related risk/);
  assert.match(m.store.notifications[0].text, /not a confirmed road closure/);
  await m.run('RX-1042'); await m.run('RX-1042');
  assert.equal(calls.photon, 1, 'duplicate updates must not re-notify'); assert.equal(calls.alt, 1, 'alternatives cached');
  assert.equal(m.store.list().length, 1);
  m.getFires = async () => ({ status: 'empty', fires: [], errors: [], sources: [], days: 2 });
  const r = await m.run('RX-1042');
  assert.equal(r.warnings[0].status, 'resolved'); assert.equal(calls.photon, 2, 'resolution message sent once');
  await m.run('RX-1042'); assert.equal(calls.photon, 2);
});

test('Photon missing recipient keeps the alert as a draft, never "sent"', async () => {
  const { m, calls } = monitorWith({ shipment: ship({ contacts: [] }) });
  const out = await m.run('RX-1042');
  assert.equal(out.warnings[0].notifications[0].status, 'drafted'); assert.match(out.warnings[0].notifications[0].reason, /No recipient/);
  assert.equal(calls.photon, 0);
  const noCfg = await sendPhotonText({ config: { apiKey: '' }, spaceId: 'x', text: 't', idempotencyKey: 'k' });
  assert.equal(noCfg.status, 'drafted');
});

test('Photon failed delivery is recorded as failed and retried at most 3 times', async () => {
  let n = 0;
  const fetchImpl = async () => { n++; return new Response(JSON.stringify({ code: 'NOT_AUTHENTICATED', status: 401, title: 'Not Authenticated' }), { status: 401 }); };
  const { m } = monitorWith({ fetchImpl });
  const out = await m.run('RX-1042');
  assert.equal(out.warnings[0].notifications[0].status, 'failed'); assert.match(out.warnings[0].notifications[0].reason, /Not Authenticated/);
  m.store.warnings.values().next().value.notifications = []; // force re-notify path
  for (let i = 0; i < 5; i++) { m.store.upsert('RX-1042|' + out.warnings[0].fire.eventId, { ...out.warnings[0], risk: 'high' }, 'x'); await m.notify(m.shipment('RX-1042'), m.store.list()[0], 'new'); }
  assert.equal(n, 3);
});

test('Photon request uses the documented endpoint, headers and body', async () => {
  let seen;
  const res = await sendPhotonText({ config: { ...{ apiKey: 'pho_sk_x', projectId: 'pho_prj_1', senderId: 'pho_usr_1', base: 'https://api.photon.codes' } }, spaceId: 'pho_spc_1', text: 'hi', idempotencyKey: 'abc', fetchImpl: async (url, opts) => { seen = { url, opts }; return new Response('{"id":"pho_msg_1","status":"dispatched"}', { status: 202 }); } });
  assert.equal(seen.url, 'https://api.photon.codes/v1/projects/pho_prj_1/messages');
  assert.equal(seen.opts.headers.Authorization, 'Bearer pho_sk_x'); assert.equal(seen.opts.headers['idempotency-key'], 'abc');
  assert.deepEqual(JSON.parse(seen.opts.body), { senderId: 'pho_usr_1', spaceId: 'pho_spc_1', content: { type: 'text', format: 'plain', text: 'hi' } });
  assert.equal(res.status, 'submitted'); assert.equal(res.photonMessageId, 'pho_msg_1');
});
