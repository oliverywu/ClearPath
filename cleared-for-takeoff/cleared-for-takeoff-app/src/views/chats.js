// Max: iMessage-style texting with the Max assistant (via the Photon messaging integration).
import { $, $$, esc, ago, load, loading, errorState } from '../ui.js';
import { getMaxChats, getMaxMessages, sendMaxMessage } from '../api.js';
let chats = [], term = '', current = null;
const stamp = iso => { const d = new Date(iso); return isNaN(d) ? esc(iso) : d.toLocaleDateString('en-US', { weekday: 'short' }) + ' ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }); };
export async function renderChats(root, id) {
  if (!root.dataset.ready) {
    root.dataset.ready = 1;
    root.innerHTML = `<div class="vhead"><a class="back" href="#/">← Landing</a><div class="k">Max · your supply assistant</div><h2>Text <em>Max.</em></h2></div>
    <div class="mlay"><div class="cside"><label class="search"><input id="csearch" placeholder="Search conversations" autocomplete="off"></label><div id="clist" class="clist"></div></div>
    <section class="phone" id="thread"></section></div><div class="call" id="call" hidden></div>`;
    $('#csearch', root).oninput = e => { term = e.target.value.toLowerCase(); list(); };
    await load($('#clist', root), getMaxChats, d => { chats = d; list(); }, { emptyMsg: 'No conversations with Max yet.', label: 'Loading conversations' });
  }
  if (!id && chats.length && innerWidth > 900) { location.replace('#/max/' + chats[0].id); return; }
  root.classList.toggle('has-thread', !!id);
  thread(id);
  function list() {
    if (!chats.length) return;
    const rows = chats.filter(c => !term || (c.name + c.role + c.lastMessage).toLowerCase().includes(term));
    $('#clist', root).innerHTML = rows.length ? rows.map(c => `<a class="citem ${c.id === current ? 'sel' : ''}" href="#/max/${c.id}"><span class="av">${esc(c.initial || c.name[0])}</span>
      <div class="cm"><div class="cnm">${esc(c.name)} <span>· ${esc(c.role)}</span></div><div class="cl">${esc(c.lastMessage)}</div></div>
      <div class="cr"><time>${ago(c.updatedAt)}</time>${c.unread ? `<b class="unread">${c.unread}</b>` : ''}</div></a>`).join('') : `<div class="state">No conversations match “${esc(term)}”.</div>`;
  }
  async function thread(cid) {
    current = cid; const el = $('#thread', root);
    if (!cid) { list(); el.innerHTML = '<div class="state">Pick a conversation.</div>'; return; }
    const c = chats.find(x => x.id === cid); if (c) c.unread = 0; list();
    el.innerHTML = loading('Loading messages');
    try {
      const msgs = await getMaxMessages(cid);
      el.innerHTML = `<header class="ph-h"><a class="ph-back" href="#/max">‹</a><span class="mav">M</span><div><div class="cnm">Max</div><div class="sub">iMessage · to ${esc(c?.name || '')}, ${esc(c?.role || '')}</div></div></header>
        <div class="msgs" id="msgs"></div><div class="qr" id="qr"></div>
        <form class="ibar" id="send"><input id="msg" placeholder="iMessage" autocomplete="off"><button aria-label="Send">↑</button></form>`;
      const box = $('#msgs', el); let prev = null;
      const add = (m, animate) => { box.insertAdjacentHTML('beforeend', bubble(m, prev, animate)); prev = m; quick(m); box.scrollTop = 1e6; };
      if (!msgs.length) box.innerHTML = '<div class="state">No messages yet. Say hi to Max.</div>';
      msgs.forEach((m, i) => add(m, i >= msgs.length - 2));
      box.onclick = e => { const b = e.target.closest('[data-call]'); if (b) openCall(msgs.find(x => x.id === b.dataset.call)?.card); };
      const send = async t => {
        t = t.trim(); if (!t) return; $('#msg', el).value = ''; box.querySelector('.state')?.remove(); $('#qr', el).innerHTML = '';
        const tmp = { id: 'tmp', from: 'me', text: t, sentAt: new Date().toISOString() }; add(tmp, true); const tmpEl = box.lastElementChild; tmpEl.classList.add('pending');
        const typing = document.createElement('div'); typing.className = 'typing'; typing.innerHTML = '<i></i><i></i><i></i>';
        setTimeout(() => { box.appendChild(typing); box.scrollTop = 1e6; }, 250);
        try {
          const res = await sendMaxMessage(cid, t); tmpEl.classList.remove('pending');
          const replies = res?.replies || [];
          await new Promise(r => setTimeout(r, 700)); typing.remove();
          for (const r of replies) { add(r, true); msgs.push(r); await new Promise(x => setTimeout(x, 450)); }
          if (c) { c.lastMessage = replies.at(-1)?.text || replies.at(-1)?.card?.title || t; c.updatedAt = new Date().toISOString(); } list();
        } catch (err) { typing.remove(); tmpEl.classList.add('failed'); tmpEl.querySelector('.bt').insertAdjacentHTML('beforeend', ' <small>Not delivered</small>'); }
      };
      $('#send', el).onsubmit = e => { e.preventDefault(); send($('#msg', el).value); };
      $('#qr', el).onclick = e => { const b = e.target.closest('button'); if (b) send(b.textContent); };
      function quick(m) { $('#qr', el).innerHTML = m.from !== 'me' && m.quickReplies ? m.quickReplies.map(q => `<button>${esc(q)}</button>`).join('') : ''; }
    } catch (e) { el.innerHTML = errorState(e, 'cretry'); $('#cretry').onclick = () => thread(cid); }
  }
  function openCall(card) {
    if (!card) return; const ov = $('#call', root); ov.hidden = false;
    ov.innerHTML = `<div class="callbox"><div class="k live">● Live transcript</div><div class="cnm" style="font-size:20px;margin:6px 0 2px">${esc(card.title)}</div><div class="sub">${esc(card.body || '')}</div>
      <div class="tr" id="tr"></div><div class="callbtns"><button class="cb" id="mute">Mute</button><button class="cb end" id="end">End</button></div></div>`;
    const tr = $('#tr', ov); let i = 0;
    const tick = () => { if (ov.hidden || i >= card.transcript.length) return; const [w, t] = card.transcript[i++]; tr.insertAdjacentHTML('beforeend', `<p class="${w === 'Max' ? 'mx' : ''}"><b>${esc(w)}</b>${esc(t)}</p>`); tr.scrollTop = 1e6; setTimeout(tick, 900); };
    tick();
    $('#mute', ov).onclick = e => { e.target.classList.toggle('on'); e.target.textContent = e.target.classList.contains('on') ? 'Muted' : 'Mute'; };
    $('#end', ov).onclick = () => { ov.hidden = true; };
  }
}
function bubble(m, prev, animate) {
  const me = m.from === 'me', gap = !prev || (new Date(m.sentAt) - new Date(prev.sentAt)) > 30 * 60e3;
  const grouped = prev && prev.from === m.from && !gap;
  let inner = m.text ? `<div class="bt">${esc(m.text)}</div>` : '';
  const c = m.card;
  if (c?.type === 'plan') inner += `<div class="card ${c.tone || ''}"><div class="ct">${esc(c.title)}</div>${c.rows.map(([k, v]) => `<div class="row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('')}</div>`;
  if (c?.type === 'options') inner += `<div class="card"><div class="ct">${esc(c.title)}</div><ol>${c.options.map(o => `<li>${esc(o)}</li>`).join('')}</ol></div>`;
  if (c?.type === 'rule') inner += `<div class="card"><span class="rchip">${esc(c.chip)}</span><div class="ct">${esc(c.title)}</div><p>${esc(c.body)}</p></div>`;
  if (c?.type === 'call') inner += `<div class="card"><div class="ct">📞 ${esc(c.title)}</div><p>${esc(c.body)}</p><button class="join" data-call="${m.id}">Open live transcript</button></div>`;
  if (m.links) inner += `<div class="blinks">${m.links.map(l => `<a href="${esc(l.href)}">${esc(l.label)} ›</a>`).join('')}</div>`;
  return `${gap ? `<div class="stamp">${stamp(m.sentAt)}</div>` : ''}<div class="b ${me ? 'me' : 'them'} ${grouped ? 'grp' : ''} ${animate ? 'anim' : ''}">${inner}${m.caption ? `<div class="cap">${esc(m.caption)}</div>` : ''}</div>`;
}
