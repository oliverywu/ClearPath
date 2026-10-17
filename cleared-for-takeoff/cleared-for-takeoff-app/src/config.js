// Single switch between mock data and the real backend.
// The integrated app uses the real unified API (USE_MOCK = false). For isolated frontend
// development without the backend, open the site with ?mock=1 to use src/mock/*.json.
const MOCK_DEFAULT = false;
export const USE_MOCK = MOCK_DEFAULT || new URLSearchParams(location.search).has('mock');
export const API_BASE = '/api';            // one same-origin API surface; the Node server proxies it
export const MOCK_LATENCY_MS = [250, 650]; // simulated latency range for mocks
// Debug helpers: ?fail=1 forces API errors, ?empty=1 forces empty lists (mock mode only).

// Google Maps (Routes / live tracking section). Leave empty to use the SVG arc fallback.
// NEVER commit a real key. Prefer src/config.local.js (gitignored) — see README.
export const GOOGLE_MAPS_API_KEY = '';
// Set true after creating src/config.local.js (exports GOOGLE_MAPS_API_KEY); off by default so no 404 is requested.
export const LOAD_LOCAL_CONFIG = false;
