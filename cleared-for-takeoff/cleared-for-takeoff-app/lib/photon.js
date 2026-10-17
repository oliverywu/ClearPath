// Photon (Beta) messaging. POST https://api.photon.codes/v1/projects/{projectId}/messages
// Auth: Authorization: Bearer <project key pho_sk_...>; required header idempotency-key.
// Body: { senderId: pho_usr_..., spaceId: pho_spc_..., content: { type: 'text', format: 'plain', text } }
// 202 = persisted for asynchronous delivery. We record that as "submitted", never as "delivered".
export const PHOTON_BASE = 'https://api.photon.codes';
export function photonConfig(env = process.env) {
  return { apiKey: env.PHOTON_API_KEY || '', projectId: env.PHOTON_PROJECT_ID || '', senderId: env.PHOTON_SENDER_ID || '', defaultSpaceId: env.PHOTON_SPACE_ID || '', base: env.PHOTON_API_BASE || PHOTON_BASE };
}
export async function sendPhotonText({ config, spaceId, text, idempotencyKey, fetchImpl = fetch }) {
  const missing = [!config.apiKey && 'PHOTON_API_KEY', !config.projectId && 'PHOTON_PROJECT_ID', !config.senderId && 'PHOTON_SENDER_ID'].filter(Boolean);
  if (missing.length) return { status: 'drafted', reason: `Photon not configured (${missing.join(', ')} missing); message drafted, not sent.` };
  if (!spaceId) return { status: 'drafted', reason: 'No recipient: shipment has no Photon space (PHOTON_SPACE_ID or contact photonSpaceId); message drafted, not sent.' };
  try {
    const r = await fetchImpl(`${config.base}/v1/projects/${encodeURIComponent(config.projectId)}/messages`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${config.apiKey}`, 'Content-Type': 'application/json', Accept: 'application/json', 'idempotency-key': idempotencyKey },
      body: JSON.stringify({ senderId: config.senderId, spaceId, content: { type: 'text', format: 'plain', text } }),
      signal: AbortSignal.timeout(15_000)
    });
    const body = await r.json().catch(() => ({}));
    if (r.status >= 200 && r.status < 300) return { status: 'submitted', photonMessageId: body.id || null, photonStatus: body.status || null, httpStatus: r.status };
    return { status: 'failed', httpStatus: r.status, reason: `Photon rejected the message: ${body.title || `HTTP ${r.status}`}${body.detail ? ` (${body.detail})` : ''}`, code: body.code || null };
  } catch (e) {
    return { status: 'failed', reason: `Photon request failed: ${e.message}` };
  }
}
const fmt = iso => iso ? new Date(iso).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' ET' : 'unknown time';
export function buildAlertText({ shipment, warning, kind = 'new' }) {
  const f = warning.fire, id = shipment.id;
  if (kind === 'resolved') return `Update for shipment ${id}: NASA FIRMS no longer shows the fire detection near its route (${f.segment}). Current ETA: ${fmt(warning.eta)}.`;
  const impact = f.revisedEta ? `If rerouted, the estimated delivery is ${fmt(f.revisedEta)} (about ${f.delayMinutes} min later).` : 'The delay is unconfirmed.';
  const lead = kind === 'update' ? `Update: risk for shipment ${id} is now ${warning.risk}. ` : '';
  return `${lead}Shipment ${id} may experience a delay due to a fire-related risk near its planned route. NASA FIRMS detected a fire at ${f.lat.toFixed(3)}, ${f.lng.toFixed(3)}${f.place ? ` (${f.place})` : ''}, ${f.distanceKm.toFixed(1)} km from the route ${f.segment}, observed ${fmt(f.observedAt)}, confidence ${f.confidence}. This is a satellite detection, not a confirmed road closure. ${impact} We are assessing the potential impact and will share an updated delivery estimate when more information becomes available.`;
}
