// Matches NASA FIRMS detections against a route corridor and grades potential risk.
// A FIRMS detection is a satellite heat signal. It is never treated as a confirmed road closure.
import { nearestOnRoute, cumulativeKm, sliceRoute, pointDistanceKm } from './geo.js';
const LEVEL = { none: 0, low: 1, medium: 2, high: 3 };
export const riskRank = r => LEVEL[r] ?? 0;
const CONF = { high: 3, nominal: 2, unknown: 1, low: 0 };

export function gradeFire({ distanceKm, confidence, frpMW, ahead, outdated }) {
  if (outdated) return 'low';
  if (!ahead) return 'low';
  let level = distanceKm <= 3 ? 3 : distanceKm <= 10 ? 2 : 1;
  if (confidence === 'low') level = Math.max(1, level - 1);
  if (frpMW !== null && frpMW >= 50 && distanceKm <= 10) level = 3;
  return ['none', 'low', 'medium', 'high'][level];
}

/** Name the stretch of the route a km position falls in, using the shipment's stops. */
export function segmentLabel(stops, fromKm, toKm) {
  const sorted = [...stops].sort((a, b) => a.alongKm - b.alongKm);
  const before = [...sorted].reverse().find(s => s.alongKm <= fromKm) || sorted[0];
  const after = sorted.find(s => s.alongKm >= toKm) || sorted[sorted.length - 1];
  if (!before || !after) return `km ${Math.round(fromKm)}–${Math.round(toKm)}`;
  return before === after ? `near ${before.name}` : `between ${before.name} and ${after.name}`;
}
export function nearestPlace(stops, point) {
  let best = null;
  for (const s of stops) { const d = pointDistanceKm(point, s); if (!best || d < best.km) best = { name: s.name, km: d }; }
  return best;
}

/**
 * @returns {{ fires, events, ignoredFar, ignoredOutdated }}
 * fires: detections inside the corridor (with distance, along-route km, risk)
 * events: fires clustered into one event per stretch of road (dedupe unit for warnings).
 */
export function analyzeFires({ points, fires, corridorKm = 25, traveledKm = 0, stops = [], now = Date.now(), maxAgeHours = 48, cum = cumulativeKm(points) }) {
  let ignoredFar = 0, ignoredOutdated = 0;
  const near = [];
  for (const f of fires) {
    const n = nearestOnRoute(f, points, cum);
    if (n.distanceKm > corridorKm) { ignoredFar++; continue; }
    const ageH = f.observedAt ? (now - Date.parse(f.observedAt)) / 3600_000 : Infinity;
    const outdated = !(ageH <= maxAgeHours);
    if (outdated) ignoredOutdated++;
    const ahead = n.alongKm >= traveledKm - 1;
    const risk = gradeFire({ distanceKm: n.distanceKm, confidence: f.confidence, frpMW: f.frpMW, ahead, outdated });
    near.push({ ...f, distanceKm: +n.distanceKm.toFixed(2), alongKm: +n.alongKm.toFixed(1), routePoint: n.point, ahead, outdated, ageHours: Number.isFinite(ageH) ? +ageH.toFixed(1) : null, risk });
  }
  near.sort((a, b) => a.alongKm - b.alongKm);
  // Cluster detections whose route positions are within 8 km of each other.
  const groups = [];
  for (const f of near) {
    const g = groups[groups.length - 1];
    if (g && f.alongKm - g[g.length - 1].alongKm <= 8) g.push(f); else groups.push([f]);
  }
  const events = groups.map(g => {
    const closest = g.reduce((a, b) => (b.distanceKm < a.distanceKm ? b : a));
    const risk = g.reduce((m, f) => (riskRank(f.risk) > riskRank(m) ? f.risk : m), 'none');
    const fromKm = Math.max(0, g[0].alongKm - 5), toKm = Math.min(cum[cum.length - 1], g[g.length - 1].alongKm + 5);
    const latest = g.reduce((m, f) => (f.observedAt && f.observedAt > m ? f.observedAt : m), '');
    const maxFrp = g.reduce((m, f) => (f.frpMW !== null && f.frpMW > (m ?? -1) ? f.frpMW : m), null);
    const bestConf = g.reduce((m, f) => (CONF[f.confidence] > CONF[m] ? f.confidence : m), 'low');
    // Stable id: 0.25° grid cell of the closest pixel, so new detections of the same fire dedupe.
    const id = `fire-${Math.round(closest.lat * 4)}_${Math.round(closest.lng * 4)}`;
    const place = stops.length ? nearestPlace(stops, closest) : null;
    return {
      id, type: 'wildfire', label: 'Satellite fire detection (NASA FIRMS)',
      lat: closest.lat, lng: closest.lng, distanceKm: closest.distanceKm, alongKm: closest.alongKm,
      detections: g.length, fireIds: g.map(f => f.id), observedAt: latest || null, confidence: bestConf, maxFrpMW: maxFrp,
      satellites: [...new Set(g.map(f => f.satellite || f.source).filter(Boolean))],
      ahead: closest.ahead, outdated: g.every(f => f.outdated), risk,
      segment: { fromKm: +fromKm.toFixed(1), toKm: +toKm.toFixed(1), label: stops.length ? segmentLabel(stops, fromKm, toKm) : `km ${Math.round(fromKm)}–${Math.round(toKm)}`, path: sliceRoute(points, cum, fromKm, toKm) },
      place: place ? `${Math.round(place.km)} km from ${place.name}` : null,
      confirmed: false, confirmation: 'potential'
    };
  }).sort((a, b) => riskRank(b.risk) - riskRank(a.risk) || a.distanceKm - b.distanceKm);
  return { fires: near, events, ignoredFar, ignoredOutdated };
}

/**
 * Compare Google alternative routes against an event. An alternative "avoids" the event when it stays
 * farther than avoidKm from every detection in the event.
 */
export function compareAlternatives({ routes, event, fires, avoidKm = 10, etaIso = null }) {
  if (!Array.isArray(routes) || !routes.length) return { available: false, reason: 'Google returned no routes for comparison.', revisedEta: null, delayMinutes: null };
  const pts = fires.filter(f => event.fireIds.includes(f.id));
  const primary = routes[0];
  const scored = routes.map((r, i) => ({ i, durationSec: r.durationSec, distanceMeters: r.distanceMeters, minKm: Math.min(...pts.map(p => nearestOnRoute(p, r.points).distanceKm)) }));
  const avoiding = scored.slice(1).filter(r => r.minKm > avoidKm).sort((a, b) => a.durationSec - b.durationSec)[0];
  if (scored[0].minKm > avoidKm) return { available: true, primaryAvoids: true, primaryDurationSec: primary.durationSec, alternativeDurationSec: primary.durationSec, delayMinutes: 0, revisedEta: etaIso, reason: 'The current Google route already stays clear of the detection.' };
  if (!avoiding) return { available: false, primaryDurationSec: primary.durationSec, alternatives: routes.length - 1, revisedEta: null, delayMinutes: null, reason: routes.length > 1 ? 'Google alternatives also pass near the detection.' : 'Google returned no alternative route.' };
  const delayMinutes = Math.max(0, Math.round((avoiding.durationSec - primary.durationSec) / 60));
  const revisedEta = etaIso ? new Date(Date.parse(etaIso) + delayMinutes * 60_000).toISOString() : null;
  return { available: true, primaryAvoids: false, primaryDurationSec: primary.durationSec, alternativeDurationSec: avoiding.durationSec, alternativeDistanceMeters: avoiding.distanceMeters, alternativeMinKm: +avoiding.minKm.toFixed(1), delayMinutes, revisedEta, alternativeIndex: avoiding.i, reason: `An alternative route avoids the area and adds about ${delayMinutes} min.` };
}
