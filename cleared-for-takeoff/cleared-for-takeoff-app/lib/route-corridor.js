import { greatCircle, cumulativeKm } from './geo.js';

// Representative coordinates (main city / air hub) for place names used by shipments whose
// legs Google cannot drive (overseas, islands, bare country names). Used only for an
// estimated air/sea corridor when Google Routes returns no road route.
export const PLACE_COORDS = {
  'boston': { lat: 42.36, lng: -71.01 }, 'indianapolis': { lat: 39.72, lng: -86.29 },
  'puerto rico': { lat: 18.44, lng: -66.0 }, 'sao paulo': { lat: -23.43, lng: -46.47 },
  'mumbai': { lat: 19.09, lng: 72.87 }, 'berlin': { lat: 52.36, lng: 13.5 }, 'tokyo': { lat: 35.77, lng: 140.39 },
  'argentina': { lat: -34.82, lng: -58.54 }, 'austria': { lat: 48.11, lng: 16.57 }, 'australia': { lat: -33.94, lng: 151.18 },
  'belgium': { lat: 50.9, lng: 4.48 }, 'canada': { lat: 43.68, lng: -79.63 }, 'switzerland': { lat: 47.46, lng: 8.55 },
  'china': { lat: 31.14, lng: 121.8 }, 'denmark': { lat: 55.62, lng: 12.65 }, 'spain': { lat: 40.47, lng: -3.57 },
  'finland': { lat: 60.32, lng: 24.95 }, 'france': { lat: 49.01, lng: 2.55 }, 'united kingdom': { lat: 51.47, lng: -0.45 },
  'ireland': { lat: 53.42, lng: -6.27 }, 'italy': { lat: 45.63, lng: 8.72 }, 'south korea': { lat: 37.46, lng: 126.44 },
  'netherlands': { lat: 52.31, lng: 4.76 }, 'new zealand': { lat: -37.01, lng: 174.79 }, 'singapore': { lat: 1.36, lng: 103.99 },
  'mexico': { lat: 19.44, lng: -99.07 }, 'united states': { lat: 39.83, lng: -98.58 }, 'germany': { lat: 50.04, lng: 8.56 },
  'japan': { lat: 35.77, lng: 140.39 }, 'india': { lat: 19.09, lng: 72.87 }, 'brazil': { lat: -23.43, lng: -46.47 }
};
const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();

/** Coordinates for a place name: known shipment stops first, then the table (full name, then each comma part). */
export function resolvePlace(name, shipments = []) {
  const n = norm(name);
  for (const s of shipments) for (const stop of s.stops || []) if (norm(stop.name) === n && Number.isFinite(stop.lat)) return { lat: stop.lat, lng: stop.lng };
  if (PLACE_COORDS[n]) return PLACE_COORDS[n];
  for (const part of n.split(',').map(p => p.trim())) if (PLACE_COORDS[part]) return PLACE_COORDS[part];
  return null;
}

/** Great-circle corridor between two named places, or null when either cannot be located. */
export function estimatedCorridor(origin, destination, shipments = []) {
  const a = resolvePlace(origin, shipments), b = resolvePlace(destination, shipments);
  if (!a || !b) return null;
  const points = greatCircle(a, b, 256);
  return { points, distanceMeters: Math.round(cumulativeKm(points).at(-1) * 1000) };
}
