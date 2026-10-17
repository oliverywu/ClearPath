// NASA FIRMS active-fire client (official Area API, CSV).
// https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{days}
// The 2020 Disasters Mapping Portal MapServer (firms_ca_fires_2020) is a historical California archive
// and is NOT used for current monitoring.
export const FIRMS_SOURCES = ['VIIRS_SNPP_NRT', 'VIIRS_NOAA20_NRT', 'MODIS_NRT'];
export const FIRMS_BASE = 'https://firms.modaps.eosdis.nasa.gov/api/area/csv';
const cache = new Map();
export function clearFirmsCache() { cache.clear(); }

export function parseFirmsCsv(text, source = '') {
  const lines = String(text || '').trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 1) return [];
  const header = lines[0].split(',').map(h => h.trim().toLowerCase());
  if (!header.includes('latitude') || !header.includes('longitude')) {
    // FIRMS answers errors (bad key, quota) as plain text with 200/400.
    throw Object.assign(new Error(`FIRMS returned an unexpected response: ${lines[0].slice(0, 120)}`), { code: 'FIRMS_BAD_RESPONSE' });
  }
  const out = [];
  for (const line of lines.slice(1)) {
    const cols = line.split(','), row = Object.fromEntries(header.map((h, i) => [h, (cols[i] ?? '').trim()]));
    const lat = Number(row.latitude), lng = Number(row.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    const t = String(row.acq_time || '0000').padStart(4, '0');
    const observedAt = row.acq_date ? new Date(`${row.acq_date}T${t.slice(0, 2)}:${t.slice(2)}:00Z`).toISOString() : null;
    out.push({
      id: `${source || row.instrument || 'FIRMS'}:${lat.toFixed(4)},${lng.toFixed(4)}@${row.acq_date || ''}T${t}`,
      lat, lng, observedAt,
      confidence: normalizeConfidence(row.confidence),
      confidenceRaw: row.confidence || null,
      frpMW: row.frp !== undefined && row.frp !== '' && Number.isFinite(Number(row.frp)) ? Number(row.frp) : null,
      brightnessK: Number(row.bright_ti4 || row.brightness) || null,
      satellite: row.satellite || null, instrument: row.instrument || null,
      daynight: row.daynight || null, source: source || null
    });
  }
  return out;
}
/** VIIRS uses l/n/h; MODIS uses 0-100. */
export function normalizeConfidence(v) {
  const s = String(v ?? '').trim().toLowerCase();
  if (['h', 'high'].includes(s)) return 'high';
  if (['n', 'nominal'].includes(s)) return 'nominal';
  if (['l', 'low'].includes(s)) return 'low';
  const n = Number(s);
  if (s !== '' && Number.isFinite(n)) return n >= 80 ? 'high' : n >= 30 ? 'nominal' : 'low';
  return 'unknown';
}

/**
 * Fetch recent detections in a bbox from all sources.
 * Returns { status: 'ok'|'empty'|'stale'|'no_key'|'error', fires, fetchedAt, newestObservation, errors, sources }.
 */
export async function getFires(box, { days = 2, key = process.env.FIRMS_MAP_KEY, fetchImpl = fetch, sources = FIRMS_SOURCES, ttlMs = 15 * 60_000, staleHours = 36, now = Date.now() } = {}) {
  const base = { fires: [], fetchedAt: new Date(now).toISOString(), newestObservation: null, errors: [], sources, days, bbox: box };
  if (!key) return { ...base, status: 'no_key', message: 'FIRMS_MAP_KEY is not set, so NASA fire detections cannot be loaded.' };
  const d = Math.max(1, Math.min(10, Math.round(days)));
  const results = await Promise.all(sources.map(async src => {
    const url = `${FIRMS_BASE}/${encodeURIComponent(key)}/${src}/${box.join(',')}/${d}`;
    const ck = `${src}|${box.join(',')}|${d}`, hit = cache.get(ck);
    if (hit && now - hit.at < ttlMs) return { src, fires: hit.fires };
    try {
      const r = await fetchImpl(url, { signal: AbortSignal.timeout(20_000) });
      const text = await r.text();
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${text.slice(0, 120)}`);
      const fires = parseFirmsCsv(text, src);
      cache.set(ck, { at: now, fires });
      return { src, fires };
    } catch (e) {
      const msg = String(e.message || e).replaceAll(key, '***');
      if (hit) return { src, fires: hit.fires, error: `${src}: ${msg} (using cached data)` };
      return { src, fires: [], error: `${src}: ${msg}` };
    }
  }));
  const fires = results.flatMap(r => r.fires), errors = results.filter(r => r.error).map(r => r.error);
  const newest = fires.reduce((m, f) => f.observedAt && f.observedAt > m ? f.observedAt : m, '') || null;
  const out = { ...base, fires, errors, newestObservation: newest };
  if (errors.length === sources.length && !fires.length) return { ...out, status: 'error', message: `NASA FIRMS unavailable: ${errors[0]}` };
  if (!fires.length) return { ...out, status: 'empty', message: `No FIRMS detections in the route area in the last ${d} day(s).` };
  if (now - Date.parse(newest) > staleHours * 3600_000) return { ...out, status: 'stale', message: `Newest FIRMS detection is older than ${staleHours} h; data may be outdated.` };
  return { ...out, status: 'ok' };
}
