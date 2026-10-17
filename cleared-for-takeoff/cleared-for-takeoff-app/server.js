import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
// Load developer-local secrets without a runtime dependency. The file is ignored by git.
try {
  const envText = await readFile(path.join(ROOT, '.env.local'), 'utf8');
  for (const line of envText.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match || match[1] in process.env) continue;
    process.env[match[1]] = match[2].replace(/^(['"])(.*)\1$/, '$2');
  }
} catch (error) { if (error.code !== 'ENOENT') throw error; }
const PORT = Number(process.env.PORT || 8000);
const GOOGLE_MAPS_API_KEY = process.env.GOOGLE_MAPS_API_KEY || '';
const GDACS_EVENTS_URL = process.env.GDACS_EVENTS_URL || 'https://www.gdacs.org/gdacsapi/api/Events/geteventlist/EVENTS4APP';
const MAX_EVENT_AGE_DAYS = Number(process.env.DISASTER_MAX_AGE_DAYS || 30);
const MAX_BODY_BYTES = 16_384;
let eventCache;
let eventCacheAt = 0;

function send(res, status, payload, headers = {}) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...headers });
  res.end(JSON.stringify(payload));
}
async function readJson(req) {
  let body = '', size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw Object.assign(new Error('Request body is too large.'), { status: 413 });
    body += chunk;
  }
  try { return body ? JSON.parse(body) : {}; }
  catch { throw Object.assign(new Error('Request body must be valid JSON.'), { status: 400 }); }
}
function safeNumber(value) { const n = Number(value); return Number.isFinite(n) ? n : null; }
function first(...values) { return values.find(value => value !== undefined && value !== null && value !== ''); }
function normalizeEvent(feature) {
  const p = feature.properties || {}, geometry = feature.geometry || {}, coords = geometry.coordinates;
  let lat = safeNumber(first(p.latitude, p.lat)), lng = safeNumber(first(p.longitude, p.lon, p.lng));
  if (geometry.type === 'Point' && Array.isArray(coords)) { lng = safeNumber(coords[0]); lat = safeNumber(coords[1]); }
  if (lat === null || lng === null) return null;
  const levelText = String(first(p.alertlevel, p.alertLevel, p.severity?.alertlevel, 'green')).toLowerCase();
  const severity = ['red', 'orange', 'green'].find(level => levelText.includes(level)) || 'green';
  const type = String(first(p.eventtype, p.eventType, p.type, 'Other')).toUpperCase();
  const dateValue = first(p.from, p.eventdate, p.date, p.updated, p.to);
  const date = dateValue ? new Date(dateValue) : null;
  const timestamp = date && Number.isFinite(+date) ? date.toISOString() : null;
  if (timestamp && +date < Date.now() - MAX_EVENT_AGE_DAYS * 86_400_000) return null;
  return {
    id: String(first(p.eventid, p.eventId, p.id, feature.id, `${type}-${lat}-${lng}`)),
    type,
    title: String(first(p.name, p.title, p.description, `${type} event`)),
    country: String(first(p.country, p.countryname, p.countryName, 'Area not specified')),
    affectedArea: String(first(p.affectedarea, p.affectedArea, p.countryname, p.countryName, '')),
    severity, lat, lng, radiusKm: Math.max(0, safeNumber(first(p.radius, p.radiusKm, p.severity?.radius)) || 0),
    timestamp, details: String(first(p.description, p.htmldescription, ''))
  };
}
async function getEvents() {
  if (eventCache && Date.now() - eventCacheAt < 10 * 60_000) return eventCache;
  const response = await fetch(GDACS_EVENTS_URL, { headers: { Accept: 'application/geo+json, application/json' }, signal: AbortSignal.timeout(20_000) });
  if (!response.ok) throw Object.assign(new Error(`GDACS feed returned ${response.status}.`), { status: 502 });
  const data = await response.json();
  const features = Array.isArray(data.features) ? data.features : Array.isArray(data) ? data : [];
  eventCache = features.map(normalizeEvent).filter(Boolean);
  eventCacheAt = Date.now();
  return eventCache;
}
function decodePolyline(encoded) {
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
const radians = degrees => degrees * Math.PI / 180;
function pointDistanceKm(a, b) {
  const dLat = radians(b.lat - a.lat), dLng = radians(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(radians(a.lat)) * Math.cos(radians(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}
function segmentDistanceKm(point, a, b) {
  const scaleX = Math.cos(radians(point.lat));
  const ax = radians(a.lng - point.lng) * scaleX, ay = radians(a.lat - point.lat);
  const bx = radians(b.lng - point.lng) * scaleX, by = radians(b.lat - point.lat);
  const dx = bx - ax, dy = by - ay;
  const t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(ax + t * dx, ay + t * dy) * 6371;
}
function distanceFromRouteKm(event, points) {
  if (points.length === 1) return pointDistanceKm(event, points[0]);
  let nearest = Infinity;
  for (let i = 1; i < points.length; i++) nearest = Math.min(nearest, segmentDistanceKm(event, points[i - 1], points[i]));
  return nearest;
}
async function analyzeRoute(body) {
  const origin = typeof body.origin === 'string' ? body.origin.trim() : '';
  const destination = typeof body.destination === 'string' ? body.destination.trim() : '';
  const proximityKm = safeNumber(body.proximityKm);
  if (!origin || !destination || origin.length > 300 || destination.length > 300) throw Object.assign(new Error('Origin and destination are required (maximum 300 characters each).'), { status: 400 });
  if (proximityKm === null || proximityKm < 1 || proximityKm > 500) throw Object.assign(new Error('proximityKm must be between 1 and 500.'), { status: 400 });
  if (!GOOGLE_MAPS_API_KEY) throw Object.assign(new Error('Server configuration is missing GOOGLE_MAPS_API_KEY.'), { status: 503 });
  const response = await fetch(`https://routes.googleapis.com/directions/v2:computeRoutes?key=${encodeURIComponent(GOOGLE_MAPS_API_KEY)}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Goog-FieldMask': 'routes.polyline.encodedPolyline,routes.distanceMeters,routes.duration' },
    body: JSON.stringify({ origin: { address: origin }, destination: { address: destination }, travelMode: 'DRIVE', polylineQuality: 'HIGH_QUALITY' }),
    signal: AbortSignal.timeout(20_000)
  });
  const routeData = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = routeData.error?.message || `HTTP ${response.status}`;
    throw Object.assign(new Error(`Google Routes API rejected the request: ${detail}`), { status: 502 });
  }
  const route = routeData.routes?.[0];
  if (!route?.polyline?.encodedPolyline) throw Object.assign(new Error('Google Routes API returned no route geometry.'), { status: 502 });
  const points = decodePolyline(route.polyline.encodedPolyline);
  const events = await getEvents();
  const severityOrder = { red: 0, orange: 1, green: 2 };
  const nearbyEvents = events.map(event => ({ ...event, distanceKm: Number(distanceFromRouteKm(event, points).toFixed(1)) }))
    .filter(event => event.distanceKm <= proximityKm + event.radiusKm)
    .sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity] || a.distanceKm - b.distanceKm);
  return {
    origin, destination, distanceMeters: route.distanceMeters || null, duration: route.duration || null,
    routePointCount: points.length, proximityKm, eventsChecked: events.length, events: nearbyEvents,
    analyzedAt: new Date().toISOString()
  };
}
const MIME = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml' };
async function serveStatic(req, res, pathname) {
  const requested = pathname === '/' ? '/index.html' : decodeURIComponent(pathname);
  if (requested.split('/').some(part => part.startsWith('.'))) return send(res, 404, { error: 'Not found.' });
  const filename = path.resolve(ROOT, `.${requested}`);
  if (!filename.startsWith(`${ROOT}${path.sep}`)) return send(res, 403, { error: 'Forbidden.' });
  try {
    const contents = await readFile(filename);
    res.writeHead(200, { 'Content-Type': MIME[path.extname(filename)] || 'application/octet-stream', 'X-Content-Type-Options': 'nosniff' });
    if (req.method === 'HEAD') return res.end();
    res.end(contents);
  } catch { send(res, 404, { error: 'Not found.' }); }
}
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  if (url.pathname === '/api/route-analysis') {
    if (req.method !== 'POST') return send(res, 405, { error: 'Method not allowed.' }, { Allow: 'POST' });
    try { return send(res, 200, await analyzeRoute(await readJson(req))); }
    catch (error) { return send(res, error.status || 502, { error: error.message || 'Route analysis failed.' }); }
  }
  if (!['GET', 'HEAD'].includes(req.method)) return send(res, 405, { error: 'Method not allowed.' }, { Allow: 'GET, HEAD' });
  return serveStatic(req, res, url.pathname);
});
server.listen(PORT, () => console.log(`Cleared for Takeoff listening on http://localhost:${PORT}`));
