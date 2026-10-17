// HTTP handlers for shipment intelligence (FIRMS + tracking + warnings + Photon alerts).
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { FireMonitor } from './monitor.js';
import { IntelStore } from './store.js';
export function createIntel(root, env = process.env) {
  const shipments = JSON.parse(readFileSync(path.join(root, 'src/mock/live-shipments.json'), 'utf8'));
  const monitor = new FireMonitor({ shipments, env, store: new IntelStore(path.join(root, '.data/fire-intel.json')) });
  let timer = null;
  function start() {
    const minutes = Math.max(5, Number(env.FIRMS_REFRESH_MINUTES || 15));
    if (!env.GOOGLE_MAPS_API_KEY || !env.FIRMS_MAP_KEY) { console.log('Fire monitor: background refresh off (needs GOOGLE_MAPS_API_KEY and FIRMS_MAP_KEY).'); return; }
    const tick = () => monitor.runAll().then(r => console.log(`Fire monitor: checked ${r.length} shipment(s) at ${new Date().toISOString()}`)).catch(e => console.warn('Fire monitor:', e.message));
    tick(); timer = setInterval(tick, minutes * 60_000); timer.unref?.();
  }
  async function handle(req, res, url, send) {
    const p = url.pathname;
    if (!p.startsWith('/api/') ) return false;
    const getOnly = () => { if (req.method !== 'GET') { send(res, 405, { error: 'Method not allowed.' }, { Allow: 'GET' }); return false; } return true; };
    try {
      if (p === '/api/maps-config') { if (getOnly()) send(res, 200, { browserKey: env.GOOGLE_MAPS_BROWSER_KEY || '' }); return true; }
      if (p === '/api/live-shipments') { if (getOnly()) send(res, 200, shipments.map(s => ({ id: s.id, product: s.product, origin: s.origin, destination: s.destination, synthetic: !!s.synthetic }))); return true; }
      const m = p.match(/^\/api\/live-shipments\/([^/]+)\/intel$/);
      if (m) { if (getOnly()) send(res, 200, await monitor.run(decodeURIComponent(m[1]), { demo: url.searchParams.get('demo') === '1' })); return true; }
      if (p === '/api/fire-warnings') { if (getOnly()) send(res, 200, monitor.store.list()); return true; }
      if (p === '/api/photon/alerts') {
        if (getOnly()) { const msgs = monitor.alertsThread(), lastMsg = msgs[msgs.length - 1];
          send(res, 200, { chat: { id: 'max-alerts', name: 'Shipment alerts', role: 'Photon · automatic', initial: '!', unread: 0, updatedAt: lastMsg?.sentAt || new Date(monitor.bootAt).toISOString(), lastMessage: lastMsg ? `${lastMsg.status}: ${lastMsg.text.slice(0, 60)}…` : 'No shipment alerts yet.' }, messages: msgs }); }
        return true;
      }
    } catch (e) { send(res, e.status || 502, { error: e.message || 'Shipment intelligence failed.' }); return true; }
    return false;
  }
  return { monitor, handle, start, stop: () => clearInterval(timer) };
}
