// Photon (Beta) messaging. POST https://api.photon.codes/v1/projects/{projectId}/messages
// Auth: Authorization: Bearer <project key pho_sk_...>; required header idempotency-key.
// Body: { senderId: pho_usr_..., spaceId: pho_spc_..., content: { type: 'text', format: 'plain', text } }
// 202 = persisted for asynchronous delivery. We record that as "submitted", never as "delivered".
export const PHOTON_BASE = 'https://api.photon.codes';
export function photonConfig(env = process.env) {
  return { apiKey: env.PHOTON_API_KEY || '', projectId: env.PHOTON_PROJECT_ID || '', senderId: env.PHOTON_SENDER_ID || '', defaultSpaceId: env.PHOTON_SPACE_ID || '', base: env.PHOTON_API_BASE || PHOTON_BASE };
}
const ID = { PHOTON_PROJECT_ID: 'pho_prj_', PHOTON_SENDER_ID: 'pho_usr_' };
const ULID = /^[0-7][0-9a-hjkmnp-tv-z]{25}$/;
const looksPlaceholder = v => /x{4,}|your|placeholder|changeme|<|>/i.test(v);
const prefixOf = v => (String(v).match(/^[a-z]+_[a-z]+_/) || [''])[0];
/** Problems with the Photon config, never including secret values (only id prefixes). */
export function photonProblems(config) {
  const out = [];
  if (!config.apiKey) out.push('PHOTON_API_KEY missing');
  else if (!config.apiKey.startsWith('pho_sk_') || looksPlaceholder(config.apiKey)) out.push('PHOTON_API_KEY is not a project key (must start with pho_sk_)');
  for (const [name, val] of [['PHOTON_PROJECT_ID', config.projectId], ['PHOTON_SENDER_ID', config.senderId]]) {
    if (!val) out.push(`${name} missing`);
    else if (!val.startsWith(ID[name]) || looksPlaceholder(val) || !ULID.test(val.slice(ID[name].length))) out.push(`${name} must be a ${ID[name]}… id${prefixOf(val) && prefixOf(val) !== ID[name] ? ` (got a ${prefixOf(val)} id)` : looksPlaceholder(val) ? ' (placeholder value)' : ''}`);
  }
  return out;
}
export function spaceProblem(spaceId) {
  if (!spaceId) return 'No recipient: shipment has no Photon space (PHOTON_SPACE_ID or contact photonSpaceId)';
  if (!spaceId.startsWith('pho_spc_') || looksPlaceholder(spaceId) || !ULID.test(spaceId.slice(8))) return `Recipient space must be a pho_spc_… id${looksPlaceholder(spaceId) ? ' (placeholder value)' : ''}`;
  return null;
}
export async function sendPhotonText({ config, spaceId, text, idempotencyKey, fetchImpl = fetch }) {
  const problems = photonProblems(config);
  if (problems.length) return { status: 'drafted', reason: `Photon not configured: ${problems.join('; ')}. Message drafted, not sent.` };
  const sp = spaceProblem(spaceId);
  if (sp) return { status: 'drafted', reason: `${sp}. Message drafted, not sent.` };
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
  const f = warning.fire, id = shipment.label && shipment.label !== shipment.id ? `${shipment.id} (${shipment.label})` : shipment.id;
  if (kind === 'resolved') return `Update for shipment ${id}: NASA FIRMS no longer shows the fire detection near its route (${f.segment}). Current ETA: ${fmt(warning.eta)}.`;
  const impact = f.revisedEta ? `If rerouted, the estimated delivery is ${fmt(f.revisedEta)} (about ${f.delayMinutes} min later).` : 'The delay is unconfirmed.';
  const lead = kind === 'update' ? `Update: risk for shipment ${id} is now ${warning.risk}. ` : '';
  return `${lead}Shipment ${id} may experience a delay due to a fire-related risk near its planned route. NASA FIRMS detected a fire at ${f.lat.toFixed(3)}, ${f.lng.toFixed(3)}${f.place ? ` (${f.place})` : ''}, ${f.distanceKm.toFixed(1)} km from the route ${f.segment}, observed ${fmt(f.observedAt)}, confidence ${f.confidence}. This is a satellite detection, not a confirmed road closure. ${impact} We are assessing the potential impact and will share an updated delivery estimate when more information becomes available.`;
}
