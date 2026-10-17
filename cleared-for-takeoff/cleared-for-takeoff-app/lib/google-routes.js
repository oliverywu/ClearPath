// Google Routes API (server-side key, same GOOGLE_MAPS_API_KEY the route monitor already uses).
import { decodePolyline } from './geo.js';
const sec = d => Number(String(d || '0').replace('s', '')) || 0;
export async function computeRoutes({ key, origin, destination, intermediates = [], alternatives = false, fetchImpl = fetch }) {
  if (!key) throw Object.assign(new Error('Server configuration is missing GOOGLE_MAPS_API_KEY.'), { status: 503 });
  const loc = p => typeof p === 'string' ? { address: p } : { location: { latLng: { latitude: p.lat, longitude: p.lng } } };
  const body = { origin: loc(origin), destination: loc(destination), travelMode: 'DRIVE', routingPreference: 'TRAFFIC_AWARE', polylineQuality: 'HIGH_QUALITY', computeAlternativeRoutes: alternatives };
  // Google does not return alternatives when intermediates are set.
  if (!alternatives && intermediates.length) body.intermediates = intermediates.map(p => ({ ...loc(p), via: true }));
  const r = await fetchImpl(`https://routes.googleapis.com/directions/v2:computeRoutes?key=${encodeURIComponent(key)}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Goog-FieldMask': 'routes.polyline.encodedPolyline,routes.distanceMeters,routes.duration,routes.staticDuration' },
    body: JSON.stringify(body), signal: AbortSignal.timeout(20_000)
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(`Google Routes API rejected the request: ${data.error?.message || `HTTP ${r.status}`}`), { status: 502 });
  const routes = (data.routes || []).filter(x => x.polyline?.encodedPolyline).map(x => ({ points: decodePolyline(x.polyline.encodedPolyline), distanceMeters: x.distanceMeters || 0, durationSec: sec(x.duration), staticDurationSec: sec(x.staticDuration) }));
  if (!routes.length) throw Object.assign(new Error('Google Routes API returned no route geometry.'), { status: 502 });
  return routes;
}
