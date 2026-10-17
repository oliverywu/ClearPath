// Single switch between mock data and the real backend.
export const USE_MOCK = true;              // set false to call the REST API
export const API_BASE = '/api';            // e.g. 'https://api.example.com/api'
export const MOCK_LATENCY_MS = [250, 650]; // simulated latency range for mocks
// Debug helpers: add ?fail=1 to the URL to force API errors, ?empty=1 to force empty lists.
