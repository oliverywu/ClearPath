import { $, $$, esc, ago, load, loading, errorState } from '../ui.js';
import { getPhotonChats, getChatMessages, sendChatMessage } from '../api.js';
let chats = [], term = '';
const CH = { whatsapp: 'WA', slack: 'SL', email: '@', teams: 'TM', sms: 'SMS' };
export async function renderChats(root, id) {
  if (!root.dataset.ready) {
    root.dataset.ready = 1;
    root.innerHTML = `<div class="vhead"><a class="back" href="#/">← Landing</a><div class="k">Photon · connected chats</div><h2>Photon <em>chats.</em></h2></div>
    <div class="clay"><div class="cside"><label class="search"><input id="csearch" placeholder="Search chats" autocomplete="off"></label><div id="clist" class="clist"></div></div>
    <section class="thread" id="thread"></section></div>`;
    $('#csearch', root).oninput = e => { term = e.target.value.toLowerCase(); list(); };
    await load($('#clist', root), getPhotonChats, d => { chats = d; list(); }, { emptyMsg: 'No chats connected to Photon yet.', label: 'Loading chats' });
  }
  thread(id);
  function list() {
    if (!chats.length) return;
    const rows = chats.filter(c => !term || (c.name + c.role + c.lastMessage).toLowerCase().includes(term)); const cur = location.hash.split('/')[2];
    $('#clist', root).innerHTML = rows.length ? rows.map(c => `<a class="citem ${c.id === cur ? 'sel' : ''}" href="#/chats/${c.id}"><span class="av">${esc(c.name[0])}<i>${CH[c.channel] || '•'}</i></span>
      <div class="cm"><div class="cnm">${esc(c.name)} <span>· ${esc(c.role)}</span></div><div class="cl">${esc(c.lastMessage)}</div></div>
      <div class="cr"><time>${ago(c.updatedAt)}</time>${c.unread ? `<b class="unread">${c.unread}</b>` : ''}</div></a>`).join('') : '<div class="state">No chats match “' + esc(term) + '”.</div>';
  }
  async function thread(cid) {
    const el = $('#thread', root); list();
    if (!cid) { el.innerHTML = '<div class="state">Pick a conversation.</div>'; return; }
    const c = chats.find(x => x.id === cid); if (c) c.unread = 0; list();
    el.innerHTML = loading('Loading messages');
    try { const msgs = await getChatMessages(cid);
      el.innerHTML = `<header><div><div class="cnm">${esc(c?.name || cid)}</div><div class="k">${esc(c?.role || '')} · via ${esc(c?.channel || 'photon')}</div></div>
        <div>${(c?.links || []).map(l => `<a class="lchip" href="${l.startsWith('wrn') ? '#/warnings/' + l : '#/'}">${l}</a>`).join(' ')}</div></header>
        <div class="msgs" id="msgs">${msgs.length ? msgs.map(bubble).join('') : '<div class="state">No messages yet.</div>'}</div>
        <form class="inp" id="send"><input id="msg" placeholder="Message ${esc(c?.name || '')}…" autocomplete="off"><button aria-label="Send">↑</button></form>`;
      const box = $('#msgs', el); box.scrollTop = 1e6;
      $('#send', el).onsubmit = async e => { e.preventDefault(); const t = $('#msg', el).value.trim(); if (!t) return; $('#msg', el).value = '';
        const tmp = document.createElement('div'); tmp.className = 'm me pending'; tmp.textContent = t; box.querySelector('.state')?.remove(); box.appendChild(tmp); box.scrollTop = 1e6;
        try { const m = await sendChatMessage(cid, t); tmp.outerHTML = bubble(m); if (c) { c.lastMessage = t; c.updatedAt = new Date().toISOString(); } list(); }
        catch (err) { tmp.classList.add('failed'); tmp.title = err.message; tmp.textContent = t + ' — not sent'; } };
    } catch (e) { el.innerHTML = errorState(e, 'cretry'); $('#cretry').onclick = () => thread(cid); }
  }
}
const bubble = m => `<div class="bub ${m.from === 'me' ? 'me' : 'them'}">${esc(m.text)}<time>${esc(m.sentAt)}</time></div>`;
