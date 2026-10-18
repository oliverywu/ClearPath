// Shipment position. Uses real GPS when a fresh fix exists; otherwise an estimate from departure/ETA,
// or an explicit simulated demo. The label always says which one it is.
import { nearestOnRoute, pointAtKm } from './geo.js';
export const GPS_MAX_AGE_MS = 2 * 3600_000;
export function estimatePosition({ shipment, points, cum, durationSec, now = Date.now(), demo = false, demoCycleSec = 600 }) {
  const totalKm = cum[cum.length - 1];
  const dep = Date.parse(shipment.departedAt), eta = Date.parse(shipment.eta);
  let mode, label, progress, traveledKm, gpsAt = null, note = null;
  const gps = shipment.gps;
  const gpsFresh = gps && Number.isFinite(gps.lat) && Number.isFinite(gps.lng) && now - Date.parse(gps.at) <= GPS_MAX_AGE_MS;
  if (gpsFresh) {
    const n = nearestOnRoute(gps, points, cum);
    traveledKm = n.alongKm; progress = totalKm ? traveledKm / totalKm : 0; mode = 'gps'; label = 'GPS position'; gpsAt = gps.at;
    if (n.distanceKm > 5) note = `GPS fix is ${n.distanceKm.toFixed(1)} km off the planned route.`;
  } else if (demo) {
    progress = ((now / 1000) % demoCycleSec) / demoCycleSec; traveledKm = progress * totalKm; mode = 'demo'; label = 'Demo · simulated movement';
  } else if (Number.isFinite(shipment.progressOverride)) {
    progress = Math.max(0, Math.min(1, shipment.progressOverride)); traveledKm = progress * totalKm; mode = 'estimated'; label = 'Estimated position';
    note = 'No live GPS feed; position estimated from the latest tracking milestone.';
  } else if (Number.isFinite(dep) && Number.isFinite(eta) && eta > dep) {
    progress = Math.max(0, Math.min(1, (now - dep) / (eta - dep))); traveledKm = progress * totalKm; mode = 'estimated'; label = 'Estimated position';
    note = gps ? 'Last GPS fix is too old; position estimated from departure and ETA.' : 'No live GPS feed; position estimated from departure and ETA.';
  } else {
    progress = 0; traveledKm = 0; mode = 'unknown'; label = 'Position unknown'; note = 'No GPS and no departure/ETA to estimate from.';
  }
  const at = pointAtKm(points, cum, traveledKm);
  const remainingKm = Math.max(0, totalKm - traveledKm);
  const remainingSec = mode === 'gps' || mode === 'demo' ? Math.round(durationSec * (1 - progress)) : Number.isFinite(eta) ? Math.max(0, Math.round((eta - now) / 1000)) : Math.round(durationSec * (1 - progress));
  const etaOut = mode === 'gps' || mode === 'demo' ? new Date(now + remainingSec * 1000).toISOString() : shipment.eta || null;
  const stops = (shipment.stops || []).map(s => {
    const n = nearestOnRoute(s, points, cum);
    const state = n.alongKm <= traveledKm - 3 ? 'completed' : Math.abs(n.alongKm - traveledKm) < 3 ? 'current' : 'upcoming';
    return { ...s, alongKm: +n.alongKm.toFixed(1), state };
  });
  return { mode, label, note, gpsAt, progress: +progress.toFixed(4), traveledKm: +traveledKm.toFixed(1), remainingKm: +remainingKm.toFixed(1), remainingSec, totalKm: +totalKm.toFixed(1), eta: etaOut, position: at.point, splitIndex: at.index, stops, isLive: mode === 'gps' };
}
