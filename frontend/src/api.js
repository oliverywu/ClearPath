const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function getJSON(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  return response.json();
}

export function fetchScenarios() {
  return getJSON("/api/scenarios");
}

export function fetchDashboard(scenarioId) {
  return getJSON(`/api/dashboard?scenario=${encodeURIComponent(scenarioId)}`);
}
