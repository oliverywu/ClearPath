import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseFirmsCsv, getFires, clearFirmsCache, normalizeConfidence } from '../lib/firms.js';
import { analyzeFires, compareAlternatives } from '../lib/fire-analysis.js';
import { estimatePosition } from '../lib/tracking.js';
import { cumulativeKm } from '../lib/geo.js';
import { FireMonitor } from '../lib/monitor.js';
import { IntelStore } from '../lib/store.js';
import { sendPhotonText, photonProblems } from '../lib/photon.js';
import { greatCircle, chunkBoxes } from '../lib/geo.js';
import { loadShipments } from '../lib/intel-routes.js';

const PRJ = 'pho_prj_00000000000000000000000001', USR = 'pho_usr_00000000000000000000000001', SPC = 'pho_spc_00000000000000000000000001';
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
  const res = await sendPhotonText({ config: { ...{ apiKey: 'pho_sk_x', projectId: PRJ, senderId: USR, base: 'https://api.photon.codes' } }, spaceId: SPC, text: 'hi', idempotencyKey: 'abc', fetchImpl: async (url, opts) => { seen = { url, opts }; return new Response('{"id":"pho_msg_1","status":"dispatched"}', { status: 202 }); } });
  assert.equal(seen.url, `https://api.photon.codes/v1/projects/${PRJ}/messages`);
  assert.equal(seen.opts.headers.Authorization, 'Bearer pho_sk_x'); assert.equal(seen.opts.headers['idempotency-key'], 'abc');
  assert.deepEqual(JSON.parse(seen.opts.body), { senderId: USR, spaceId: SPC, content: { type: 'text', format: 'plain', text: 'hi' } });
  assert.equal(res.status, 'submitted'); assert.equal(res.photonMessageId, 'pho_msg_1');
});

test('placeholder / wrong-prefix Photon values are treated as not configured', async () => {
  const bad = { apiKey: 'sk_live_abc', projectId: PRJ, senderId: 'pho_org_00000000000000000000000001' };
  const p = photonProblems(bad);
  assert.ok(p.some(x => /pho_sk_/.test(x))); assert.ok(p.some(x => /pho_usr_.*pho_org_/.test(x)));
  assert.ok(!p.join(' ').includes('abc'), 'never echoes secret values');
  let called = false;
  const r = await sendPhotonText({ config: { ...bad, apiKey: 'pho_sk_ok' , senderId: USR }, spaceId: 'pho_spc_xxxxxxxx', text: 't', idempotencyKey: 'k', fetchImpl: async () => { called = true; } });
  assert.equal(r.status, 'drafted'); assert.match(r.reason, /placeholder/); assert.equal(called, false);
});

test('drafted alert is sent once Photon config becomes valid, then deduped', async () => {
  const env = { ...PHOTON_ENV, PHOTON_SENDER_ID: 'pho_org_00000000000000000000000001' };
  const { m, calls } = monitorWith({ env });
  const a = await m.run('RX-1042');
  assert.equal(a.warnings[0].notifications[0].status, 'drafted'); assert.equal(calls.photon, 0);
  env.PHOTON_SENDER_ID = USR; m.store.list()[0].risk = 'medium'; // force a change cycle
  await m.run('RX-1042');
  assert.equal(calls.photon, 1);
  await m.run('RX-1042'); assert.equal(calls.photon, 1);
});

test('overseas shipment uses an estimated great-circle path with FIRMS checks per chunk', async () => {
  const gc = greatCircle({ lat: 42.36, lng: -71.01 }, { lat: 35.77, lng: 140.39 }, 160);
  assert.ok(gc.some((p, i) => i && Math.abs(p.lng - gc[i - 1].lng) > 180), 'crosses antimeridian');
  const boxes = chunkBoxes(gc, 30);
  assert.ok(boxes.length > 5 && boxes.every(b => b[0] <= b[2]));
  const ships = loadShipments(new URL('..', import.meta.url).pathname);
  const jp = ships.find(s => s.id === 'shp-001');
  assert.equal(jp.pathMode, 'geodesic'); assert.ok(ships.find(s => s.id === 'RX-1042'));
  let boxCalls = 0;
  const mon = new FireMonitor({ shipments: [jp], store: new IntelStore(), env: {}, now: () => NOW, computeRoutes: async () => { throw new Error('should not call Google'); },
    getFiresImpl: async () => { boxCalls++; return { status: 'empty', fires: [], errors: [], sources: [], days: 2 }; } });
  const out = await mon.run('shp-001');
  assert.equal(out.route.estimatedPath, true); assert.equal(out.tracker.label, 'Estimated position'); assert.equal(out.tracker.progress, 0.62);
  assert.equal(boxCalls, boxes.length); assert.equal(out.firms.status, 'empty'); assert.equal(out.shipment.label, 'Japan');
});

test('Google Routes quota failure falls back to an estimated path through planned stops (FIRMS still runs)', async () => {
  const quotaFetch = async () => new Response(JSON.stringify({ error: { message: "Quota exceeded for quota metric 'ComputeRoutes per day'" } }), { status: 429 });
  const m = new FireMonitor({ shipments: [ship()], store: new IntelStore(), env: { GOOGLE_MAPS_API_KEY: 'k' }, fetchImpl: quotaFetch, now: () => NOW,
    getFiresImpl: async () => ({ status: 'ok', fires: FIRES, fetchedAt: new Date(NOW).toISOString(), newestObservation: null, errors: [], sources: [], days: 2, message: null }) });
  const d = await m.run('RX-1042');
  assert.equal(d.route.routeSource, 'estimated');
  assert.match(d.route.fallbackReason, /quota reached/);
  assert.ok(d.route.distanceMeters > 333000 * 1.15 && d.route.distanceMeters < 333000 * 1.25);
  assert.ok(d.route.traveled.length + d.route.remaining.length > 2);
  assert.ok(Array.isArray(d.fires) && d.fires.length > 0);
});

test('successful Google route is cached and reused when Google later fails', async () => {
  let calls = 0, fail = false;
  const routes = async () => { calls++; if (fail) throw new Error('Google Routes API rejected the request: Quota exceeded'); return [{ points: ROUTE, distanceMeters: 333000, durationSec: 4 * 3600 }]; };
  let t = NOW;
  const m = new FireMonitor({ shipments: [ship()], store: new IntelStore(), env: {}, computeRoutes: routes, now: () => t,
    getFiresImpl: async () => ({ status: 'ok', fires: [], fetchedAt: null, newestObservation: null, errors: [], sources: [], days: 2, message: null }) });
  assert.equal((await m.route(ship())).routeSource, 'google');
  t += 13 * 3600_000; fail = true;
  const r = await m.route(ship());
  assert.equal(r.routeSource, 'google-cached'); assert.equal(r.distanceMeters, 333000); assert.equal(calls, 2);
});

test('route corridor: overseas legs fall back to an estimated great-circle corridor', async () => {
  const { estimatedCorridor, resolvePlace } = await import('../lib/route-corridor.js');
  const c = estimatedCorridor('Indianapolis, US', 'Tokyo, JP');
  assert.ok(c && c.points.length > 100);
  assert.ok(c.distanceMeters > 10_000_000 && c.distanceMeters < 11_500_000);
  assert.deepEqual(resolvePlace('Sao Paulo, BR'), resolvePlace('São Paulo'));
  assert.ok(estimatedCorridor('Boston', 'Canada'));
  assert.equal(estimatedCorridor('Boston', 'Atlantis'), null);
});
