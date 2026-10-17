import { $, initCursor, burst } from './ui.js';
import { initLanding } from './views/landing.js';
import { renderWarnings } from './views/warnings.js';
import { renderChats } from './views/chats.js';
import { renderMonitor } from './views/monitor.js';
const ptr = initCursor();
initLanding(ptr);
let last = '';
// Hash router: #/  ·  #/warnings  ·  #/warnings/:id  ·  #/chats  ·  #/chats/:id
function route() {
  const [, view = '', id] = (location.hash || '#/').split('/');
  const name = view || 'landing';
  document.body.dataset.view = name;
  $('#v-warnings').hidden = name !== 'warnings'; $('#v-chats').hidden = name !== 'chats'; $('#v-monitor').hidden = name !== 'monitor';
  if (name !== last && last && name !== 'landing' && last !== 'landing') burst();
  if (name === 'warnings') renderWarnings($('#v-warnings'), id);
  if (name === 'chats') renderChats($('#v-chats'), id);
  if (name === 'monitor') renderMonitor($('#v-monitor'));
  last = name;
}
addEventListener('hashchange', route); route();
addEventListener('keydown', e => { if (e.key === 'Escape' && document.activeElement.tagName !== 'INPUT') location.hash = location.hash.split('/').length > 2 ? '#/' + location.hash.split('/')[1] : '#/'; });
$('#photon').addEventListener('click', e => { if (document.body.dataset.view !== 'chats') { e.preventDefault(); burst(e.clientX, e.clientY); setTimeout(() => location.hash = '#/chats', 380); } });
import { getPhotonChats } from './api.js';
getPhotonChats().then(cs => { const u = cs.reduce((a, c) => a + c.unread, 0); $('#pbadge').textContent = u; $('#pbadge').hidden = !u; }).catch(() => $('#pbadge').hidden = true);
