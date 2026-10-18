// Orchestrates route → position → NASA FIRMS → risk → warnings → Photon notifications for each shipment.
import { cumulativeKm, chunkBoxes, simplify, sliceRoute, greatCircle } from './geo.js';
import { getFires } from './firms.js';
import { analyzeFires, compareAlternatives, riskRank } from './fire-analysis.js';
import { estimatePosition } from './tracking.js';
import { computeRoutes as googleRoutes } from './google-routes.js';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
const ROUTE_DISK_TTL_MS = 12 * 3600_000;
/** Human reason for a failed Google route request. */
export function routeFailureReason(e) {
  const m = String(e?.message || '');
  if (/missing GOOGLE_MAPS_API_KEY/i.test(m)) return 'Google route key not set — showing estimated path';
  if (/quota|RESOURCE_EXHAUSTED|429/i.test(m)) return 'Google route quota reached — showing estimated path';
  if (/denied|403|not authorized|API key/i.test(m)) return 'Google route request was refused — showing estimated path';
  return 'Google route unavailable — showing estimated path';
}
/** Straight/geodesic path through planned stops; road distance ≈ 1.2 × haversine. */
export function estimatedRoute(s, reason) {
  const stops = (s.stops || []).filter(x => Number.isFinite(x.lat) && Number.isFinite(x.lng));
  if (stops.length < 2) return null;
  const points = [];
  for (let i = 1; i < stops.length; i++) { const seg = greatCircle(stops[i - 1], stops[i], 24); points.push(...(i > 1 ? seg.slice(1) : seg)); }
  const km = cumulativeKm(points).at(-1) * 1.2;
  const dep = Date.parse(s.departedAt), eta = Date.parse(s.eta);
  const durationSec = Number.isFinite(dep) && eta > dep ? Math.round((eta - dep) / 1000) : Math.round(km / 80 * 3600);
  return { points, distanceMeters: Math.round(km * 1000), durationSec, routeSource: 'estimated', fallbackReason: reason };
}
import { sendPhotonText, buildAlertText, photonConfig, photonProblems, spaceProblem } from './photon.js';
import { IntelStore } from './store.js';
const SEVERITY = { high: 'high', medium: 'medium', low: 'low' };

export class FireMonitor {
  constructor({ shipments, store = new IntelStore(), env = process.env, fetchImpl = fetch, computeRoutes, getFiresImpl, routeCacheFile = null, now = () => Date.now(), corridorKm = Number(env.FIRE_CORRIDOR_KM || 25), firmsDays = Number(env.FIRMS_DAYS || 2) } = {}) {
    Object.assign(this, { shipments, store, env, fetchImpl, now, corridorKm, firmsDays });
    this.routeCacheFile = routeCacheFile;
    this.computeRoutes = computeRoutes || (args => googleRoutes({ key: env.GOOGLE_MAPS_API_KEY, fetchImpl, ...args }));
    this.getFires = getFiresImpl || ((box, opts) => getFires(box, { key: env.FIRMS_MAP_KEY, fetchImpl, ...opts }));
    this.routeCache = new Map(); this.altCache = new Map(); this.bootAt = now(); this.last = new Map();
  }
  shipment(id) { const s = this.shipments.find(x => x.id === id); if (!s) throw Object.assign(new Error(`Unknown shipment ${id}.`), { status: 404 }); return s; }
  async route(s) {
    const hit = this.routeCache.get(s.id);
    if (hit && this.now() - hit.at < 30 * 60_000) return hit.route;
    if (s.pathMode === 'geodesic') {
      const points = greatCircle(s.coords.origin, s.coords.destination, 160), km = cumulativeKm(points).at(-1);
      const route = { points, distanceMeters: Math.round(km * 1000), durationSec: Math.round(km / 800 * 3600), estimatedPath: true };
      this.routeCache.set(s.id, { at: this.now(), route }); return route;
    }
    const disk = this.readDiskRoutes(), saved = disk[s.id];
    if (saved && this.now() - saved.at < ROUTE_DISK_TTL_MS) { const route = { ...saved.route, routeSource: 'google-cached' }; this.routeCache.set(s.id, { at: this.now(), route }); return route; }
    let route;
    try {
      [route] = await this.computeRoutes({ origin: s.originAddress || s.origin, destination: s.destinationAddress || s.destination, intermediates: (s.stops || []).filter(x => x.via).map(x => ({ lat: x.lat, lng: x.lng })) });
      route = { ...route, routeSource: 'google' };
      disk[s.id] = { at: this.now(), route }; this.writeDiskRoutes(disk);
    } catch (e) {
      const reason = routeFailureReason(e);
      if (saved) route = { ...saved.route, routeSource: 'google-cached', fallbackReason: reason.replace('showing estimated path', 'showing last saved Google route') };
      else route = estimatedRoute(s, reason);
      if (!route) throw e;
      // Retry Google sooner than the normal cache window.
      this.routeCache.set(s.id, { at: this.now() - 20 * 60_000, route }); return route;
    }
    this.routeCache.set(s.id, { at: this.now(), route }); return route;
  }
  readDiskRoutes() { if (!this.routeCacheFile) return this._mem || (this._mem = {}); try { return JSON.parse(readFileSync(this.routeCacheFile, 'utf8')); } catch { return {}; } }
  writeDiskRoutes(d) { if (!this.routeCacheFile) { this._mem = d; return; } try { mkdirSync(dirname(this.routeCacheFile), { recursive: true }); writeFileSync(this.routeCacheFile, JSON.stringify(d)); } catch {} }

  schedule(s, route) {
    if (s.schedule?.mode !== 'relative') return { departedAt: s.departedAt, eta: s.eta, scheduleNote: null };
    const dep = this.bootAt - (s.schedule.departedHoursAgo || 0) * 3600_000;
    return { departedAt: new Date(dep).toISOString(), eta: new Date(dep + route.durationSec * 1000 + (s.schedule.bufferMinutes || 0) * 60_000).toISOString(), scheduleNote: 'Demo schedule: departure anchored to server start.' };
  }
  async firesAlong(points, now) {
    const boxes = chunkBoxes(points, this.corridorKm + 5), parts = [];
    for (const b of boxes) parts.push(await this.getFires(b, { days: this.firmsDays, now }));
    if (parts.length === 1) return parts[0];
    const seen = new Set(), fires = [];
    parts.forEach(p => p.fires.forEach(f => { if (!seen.has(f.id)) { seen.add(f.id); fires.push(f); } }));
    const st = parts.map(p => p.status), errors = parts.flatMap(p => p.errors || []);
    const status = st.includes('no_key') ? 'no_key' : st.every(x => x === 'error') ? 'error' : st.includes('ok') ? 'ok' : st.includes('stale') ? 'stale' : st.includes('error') && !fires.length ? 'error' : 'empty';
    const newest = fires.reduce((m, f) => f.observedAt && f.observedAt > m ? f.observedAt : m, '') || null;
    return { ...parts[0], status, fires, errors, newestObservation: newest, boxes: boxes.length, message: parts.find(p => p.status === status)?.message || null };
  }
  async alternatives(s, event, fires, eta) {
    if (s.pathMode === 'geodesic') return { available: false, revisedEta: null, delayMinutes: null, reason: 'Estimated air/sea leg: no road alternative available.' };
    const k = `${s.id}|${event.id}`, hit = this.altCache.get(k);
    if (hit && this.now() - hit.at < 30 * 60_000) return hit.value;
    let value;
    try { const routes = await this.computeRoutes({ origin: s.originAddress || s.origin, destination: s.destinationAddress || s.destination, alternatives: true }); value = compareAlternatives({ routes, event, fires, etaIso: eta }); value.paths = routes.map(r => simplify(r.points, 150)); }
    catch (e) { value = { available: false, revisedEta: null, delayMinutes: null, reason: `Alternative route check failed: ${e.message}` }; }
    this.altCache.set(k, { at: this.now(), value }); return value;
  }
  recipients(s) {
    const cfg = photonConfig(this.env), list = s.contacts?.length ? s.contacts : [{ id: 'none', name: 'No contact on file', role: 'n/a' }];
    return list.map(c => ({ ...c, spaceId: c.photonSpaceId || (c.useDefaultSpace ? cfg.defaultSpaceId : '') }));
  }
  async notify(s, w, kind) {
    const cfg = photonConfig(this.env), out = [];
    for (const c of this.recipients(s)) {
      const dedupeKey = `${w.key}|${kind}|${w.risk}|${c.id}`;
      const prev = this.store.findNotification(dedupeKey);
      const nowValid = !photonProblems(cfg).length && !spaceProblem(c.spaceId);
      const retry = prev && ((prev.status === 'failed' && prev.attempts < 3) || (prev.status === 'drafted' && nowValid));
      if (prev && !retry) { out.push(prev); continue; } // dedupe
      const text = buildAlertText({ shipment: s, warning: w, kind });
      const res = await sendPhotonText({ config: cfg, spaceId: c.spaceId, text, idempotencyKey: dedupeKey.replace(/[^\x21-\x7e]/g, '_').slice(0, 255), fetchImpl: this.fetchImpl });
      const at = new Date(this.now()).toISOString();
      const n = prev ? Object.assign(prev, res, { attempts: prev.attempts + 1, updatedAt: at, text }) : this.store.addNotification({ id: `ntf-${this.store.notifications.length + 1}`, dedupeKey, warningId: w.id, shipmentId: s.id, kind, risk: w.risk, recipient: { id: c.id, name: c.name, role: c.role }, text, attempts: 1, createdAt: at, updatedAt: at, ...res });
      out.push(n);
    }
    w.notifications = out.map(n => ({ id: n.id, kind: n.kind, recipient: n.recipient.name, status: n.status, reason: n.reason || null, photonMessageId: n.photonMessageId || null, at: n.updatedAt }));
    return out;
  }
  async run(id, { demo = false } = {}) {
    const s = this.shipment(id), route = await this.route(s), now = this.now(), nowIso = new Date(now).toISOString();
    const sched = this.schedule(s, route), sx = { ...s, ...sched };
    const cum = cumulativeKm(route.points);
    const tracker = estimatePosition({ shipment: sx, points: route.points, cum, durationSec: route.durationSec, now, demo });
    const firms = await this.firesAlong(route.points, now);
    const usable = firms.status === 'ok' || firms.status === 'empty';
    const analysis = analyzeFires({ points: route.points, cum, fires: firms.fires, corridorKm: this.corridorKm, traveledKm: tracker.traveledKm, stops: tracker.stops, now });
    const relevant = usable ? analysis.events.filter(e => riskRank(e.risk) >= 2 && !e.outdated) : [];
    const active = new Set(), changed = [];
    for (const e of relevant) {
      const alt = await this.alternatives(s, e, analysis.fires, tracker.eta);
      const key = `${s.id}|${e.id}`; active.add(key);
      const impact = alt.revisedEta && alt.delayMinutes > 0 ? `Potential delay of about ${alt.delayMinutes} min if rerouted around the area.` : alt.primaryAvoids ? 'Route stays clear of the detection; no delay expected.' : 'Shipment may be affected; delay unconfirmed.';
      const data = {
        id: `fw-${s.id}-${e.id}`, kind: 'fire', shipmentId: s.id, countryName: s.label || s.id, requirement: 'Route fire review', study: s.study || s.product || 'Shipment', shipmentsAffected: 1,
        severity: SEVERITY[e.risk], risk: e.risk, confirmation: 'potential',
        summary: `NASA FIRMS fire detection ${e.distanceKm.toFixed(1)} km from the planned route ${e.segment.label}. Potential disruption; not a confirmed road closure.`,
        recommendedAction: alt.available && !alt.primaryAvoids ? `Consider the alternative route (+${alt.delayMinutes} min) and confirm road status with DOT/511 traffic data.` : 'Monitor; confirm road status with DOT/511 traffic data before rerouting.',
        source: 'NASA FIRMS · VIIRS/MODIS NRT', shipmentIds: [s.id], eta: tracker.eta, impact,
        fire: { eventId: e.id, lat: e.lat, lng: e.lng, distanceKm: e.distanceKm, alongKm: e.alongKm, segment: e.segment.label, segmentKm: [e.segment.fromKm, e.segment.toKm], place: e.place, observedAt: e.observedAt, confidence: e.confidence, maxFrpMW: e.maxFrpMW, satellites: e.satellites, detections: e.detections, revisedEta: alt.revisedEta && alt.delayMinutes > 0 ? alt.revisedEta : null, delayMinutes: alt.delayMinutes, alternative: { available: alt.available, reason: alt.reason, primaryDurationSec: alt.primaryDurationSec ?? null, alternativeDurationSec: alt.alternativeDurationSec ?? null } }
      };
      const { warning, change } = this.store.upsert(key, data, nowIso);
      if (change !== 'updated') changed.push([warning, change === 'new' ? 'new' : 'update']);
      else if (!warning.notifications?.length) changed.push([warning, 'new']);
      e.alt = alt;
    }
    const resolved = usable ? this.store.resolveMissing(s.id, active, nowIso) : [];
    for (const [w, kind] of changed) await this.notify(s, w, kind);
    for (const w of resolved) if (w.notifications?.some(n => n.status === 'submitted')) await this.notify(s, w, 'resolved');
    this.store.save();
    const warnings = this.store.list().filter(w => w.shipmentId === s.id);
    const result = {
      shipment: { id: s.id, label: s.label || s.id, pathMode: s.pathMode || 'road', milestones: s.milestones || null, product: s.product, study: s.study, origin: s.origin, destination: s.destination, departedAt: sched.departedAt, eta: sched.eta, scheduleNote: sched.scheduleNote, contacts: this.recipients(s).map(c => ({ name: c.name, role: c.role, hasRecipient: !!c.spaceId })) },
      route: { estimatedPath: !!route.estimatedPath, routeSource: route.routeSource || (route.estimatedPath ? 'great-circle' : 'google'), fallbackReason: route.fallbackReason || null, distanceMeters: route.distanceMeters, durationSec: route.durationSec, origin: route.points[0], destination: route.points[route.points.length - 1], traveled: simplify(sliceRoute(route.points, cum, 0, tracker.traveledKm), 250), remaining: simplify(sliceRoute(route.points, cum, tracker.traveledKm, cum[cum.length - 1]), 250) },
      tracker,
      firms: { status: firms.status, message: firms.message || null, fetchedAt: firms.fetchedAt, newestObservation: firms.newestObservation, errors: firms.errors, sources: firms.sources, days: firms.days, corridorKm: this.corridorKm, detectionsInBox: firms.fires.length, ignoredFar: analysis.ignoredFar, ignoredOutdated: analysis.ignoredOutdated },
      fires: analysis.fires.map(f => ({ id: f.id, lat: f.lat, lng: f.lng, distanceKm: f.distanceKm, alongKm: f.alongKm, observedAt: f.observedAt, confidence: f.confidence, frpMW: f.frpMW, satellite: f.satellite, instrument: f.instrument, source: f.source, daynight: f.daynight, risk: f.risk, ahead: f.ahead, outdated: f.outdated })),
      events: analysis.events.map(e => ({ ...e, segment: { ...e.segment, path: simplify(e.segment.path, 60) }, alt: e.alt ? { ...e.alt, paths: undefined, path: e.alt.alternativeIndex ? e.alt.paths?.[e.alt.alternativeIndex] : null } : null })),
      warnings, analyzedAt: nowIso, demo
    };
    this.last.set(s.id, result); return result;
  }
  async runAll() { const out = []; for (const s of this.shipments) { try { out.push(await this.run(s.id)); } catch (e) { out.push({ shipment: { id: s.id }, error: e.message }); } } return out; }
  alertsThread() {
    return this.store.notifications.slice().sort((a, b) => a.createdAt.localeCompare(b.createdAt)).map(n => ({ id: n.id, from: 'max', sentAt: n.updatedAt, text: n.text, caption: n.status === 'submitted' ? `Submitted to Photon${n.photonMessageId ? ` · ${n.photonMessageId}` : ''} · to ${n.recipient.name}` : n.status === 'drafted' ? `Drafted, not sent · ${n.reason}` : `Failed · ${n.reason}`, status: n.status, links: [{ label: 'Warning', href: `#/warnings/${n.warningId}` }] }));
  }
}
