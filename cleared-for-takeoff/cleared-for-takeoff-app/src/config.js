// Single switch between mock data and the real backend.
export const USE_MOCK = true;              // set false to call the REST API
export const API_BASE = '/api';            // e.g. 'https://api.example.com/api'
export const MOCK_LATENCY_MS = [250, 650]; // simulated latency range for mocks
// Debug helpers: add ?fail=1 to the URL to force API errors, ?empty=1 to force empty lists.

// Google Maps (Routes / live tracking section). Leave empty to use the SVG arc fallback.
// NEVER commit a real key. Prefer src/config.local.js (gitignored) — see README.
export const GOOGLE_MAPS_API_KEY = '';
// Set true after creating src/config.local.js (exports GOOGLE_MAPS_API_KEY); off by default so no 404 is requested.
export const LOAD_LOCAL_CONFIG = false;
