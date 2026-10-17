import { $, initCursor, burst } from './ui.js';
import { initLanding, refreshLanding } from './views/landing.js';
import { renderWarnings } from './views/warnings.js';
import { renderChats } from './views/chats.js';
import { renderMonitor } from './views/monitor.js';
import { initVial } from './vial.js';
const ptr = initCursor();
initLanding(ptr);
initVial();
let last = '';
// Hash router: #/  ·  #/warnings  ·  #/warnings/:id  ·  #/max  ·  #/max/:id  (#/chats → #/max)
function route() {
  const [, view = '', id] = (location.hash || '#/').split('/');
  if (view === 'chats') { location.replace('#/max' + (id ? '/' + id : '')); return; } // legacy route
  const name = view === 'max' ? 'chats' : (view || 'landing');
  document.body.dataset.view = name;
  $('#v-warnings').hidden = name !== 'warnings'; $('#v-chats').hidden = name !== 'chats'; $('#v-monitor').hidden = name !== 'monitor';
  if (name !== last && last && name !== 'landing' && last !== 'landing') burst();
  if (name === 'landing' && last && last !== 'landing') refreshLanding(); // approvals elsewhere change the plan
  if (name === 'warnings') renderWarnings($('#v-warnings'), id, last !== 'warnings');
  if (name === 'chats') renderChats($('#v-chats'), id, last !== 'chats');
  if (name === 'monitor') renderMonitor($('#v-monitor'));
  last = name;
}
addEventListener('hashchange', route); route();
addEventListener('keydown', e => { if (e.key === 'Escape' && document.activeElement.tagName !== 'INPUT') location.hash = location.hash.split('/').length > 2 ? '#/' + location.hash.split('/')[1] : '#/'; });
$('#photon').addEventListener('click', e => { if (document.body.dataset.view !== 'chats') { e.preventDefault(); burst(e.clientX, e.clientY); setTimeout(() => location.hash = '#/max', 380); } });
import { getMaxChats } from './api.js';
getMaxChats().then(cs => { const u = cs.reduce((a, c) => a + c.unread, 0); $('#pbadge').textContent = u; $('#pbadge').hidden = !u; }).catch(() => $('#pbadge').hidden = true);
