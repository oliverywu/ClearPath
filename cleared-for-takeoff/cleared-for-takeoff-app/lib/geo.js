// Geometry helpers shared by route analysis, FIRMS matching and position estimates.
export function decodePolyline(encoded) {
  let i = 0, lat = 0, lng = 0;
  const points = [];
  while (i < encoded.length) {
    let result = 0, shift = 0, b;
    do { b = encoded.charCodeAt(i++) - 63; result |= (b & 31) << shift; shift += 5; } while (b >= 32);
    lat += result & 1 ? ~(result >> 1) : result >> 1;
    result = 0; shift = 0;
    do { b = encoded.charCodeAt(i++) - 63; result |= (b & 31) << shift; shift += 5; } while (b >= 32);
    lng += result & 1 ? ~(result >> 1) : result >> 1;
    points.push({ lat: lat / 1e5, lng: lng / 1e5 });
  }
  return points;
}
const radians = d => d * Math.PI / 180;
export function pointDistanceKm(a, b) {
  const dLat = radians(b.lat - a.lat), dLng = radians(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(radians(a.lat)) * Math.cos(radians(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}
/** Distance from point to segment a-b (local equirectangular projection) and the fraction t along it. */
export function segmentProjection(point, a, b) {
  const scaleX = Math.cos(radians(point.lat));
  const ax = radians(a.lng - point.lng) * scaleX, ay = radians(a.lat - point.lat);
  const bx = radians(b.lng - point.lng) * scaleX, by = radians(b.lat - point.lat);
  const dx = bx - ax, dy = by - ay;
  const t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy || 1)));
  return { km: Math.hypot(ax + t * dx, ay + t * dy) * 6371, t };
}
export function segmentDistanceKm(point, a, b) { return segmentProjection(point, a, b).km; }
/** Cumulative km at each vertex. */
export function cumulativeKm(points) {
  const out = [0];
  for (let i = 1; i < points.length; i++) out.push(out[i - 1] + pointDistanceKm(points[i - 1], points[i]));
  return out;
}
/** Nearest location on a polyline: { distanceKm, index (segment start), alongKm, point }. */
export function nearestOnRoute(point, points, cum = cumulativeKm(points)) {
  if (points.length === 1) return { distanceKm: pointDistanceKm(point, points[0]), index: 0, alongKm: 0, point: points[0] };
  let best = { distanceKm: Infinity, index: 0, alongKm: 0, point: points[0] };
  for (let i = 1; i < points.length; i++) {
    const { km, t } = segmentProjection(point, points[i - 1], points[i]);
    if (km < best.distanceKm) best = { distanceKm: km, index: i - 1, alongKm: cum[i - 1] + t * (cum[i] - cum[i - 1]), point: lerp(points[i - 1], points[i], t) };
  }
  return best;
}
export function distanceFromRouteKm(point, points) { return nearestOnRoute(point, points).distanceKm; }
export const lerp = (a, b, t) => ({ lat: a.lat + (b.lat - a.lat) * t, lng: a.lng + (b.lng - a.lng) * t });
/** Point and vertex index at a given km along the route. */
export function pointAtKm(points, cum, km) {
  const total = cum[cum.length - 1];
  const k = Math.max(0, Math.min(total, km));
  for (let i = 1; i < points.length; i++) {
    if (cum[i] >= k) { const seg = cum[i] - cum[i - 1] || 1; return { point: lerp(points[i - 1], points[i], (k - cum[i - 1]) / seg), index: i - 1 }; }
  }
  return { point: points[points.length - 1], index: points.length - 2 };
}
/** Bounding box [west, south, east, north] padded by padKm. */
export function bbox(points, padKm = 0) {
  let w = 180, s = 90, e = -180, n = -90;
  for (const p of points) { w = Math.min(w, p.lng); e = Math.max(e, p.lng); s = Math.min(s, p.lat); n = Math.max(n, p.lat); }
  const dLat = padKm / 111, dLng = padKm / (111 * Math.max(0.2, Math.cos(radians((s + n) / 2))));
  const r = v => Math.round(v * 1000) / 1000;
  return [r(Math.max(-180, w - dLng)), r(Math.max(-90, s - dLat)), r(Math.min(180, e + dLng)), r(Math.min(90, n + dLat))];
}
/** Slice of a polyline between two along-route distances. */
export function sliceRoute(points, cum, fromKm, toKm) {
  const a = pointAtKm(points, cum, fromKm), b = pointAtKm(points, cum, toKm);
  return [a.point, ...points.slice(a.index + 1, b.index + 1), b.point];
}
/** Downsample a polyline for transport to the browser. */
export function simplify(points, max = 400) {
  if (points.length <= max) return points;
  const step = (points.length - 1) / (max - 1), out = [];
  for (let i = 0; i < max; i++) out.push(points[Math.round(i * step)]);
  return out;
}
