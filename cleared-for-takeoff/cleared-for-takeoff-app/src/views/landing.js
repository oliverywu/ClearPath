import { $, $$, esc, STATUS, fmtDate, load, burst } from '../ui.js';
import { loadGoogleMaps, buildMap } from '../map.js';
import { mountEmbed, greatCircle } from '../embed-map.js';
import { attachLiveShipments } from '../intel.js';
import { getShipments, getInventory, getWarnings, getCalendar, getDaySchedule, getChalkInsight, getTracking, getTrackingDetail } from '../api.js';
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
export function initLanding(ptr) {
  const img = $('#img'), n = $('#notif');
  // capsule text from the newest open warning
  getWarnings().then(ws => { const open = ws.filter(w => w.status !== 'resolved'); if (open[0]) $('#nsm').textContent = `${open[0].countryName} · alert 1 of ${open.length}`; }).catch(() => {});
  n.addEventListener('mousemove', e => { const r = n.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5; n.style.setProperty('--nry', x * 24 + 'deg'); n.style.setProperty('--nrx', -y * 30 + 'deg'); $('#pill').style.setProperty('--hx', (x + .5) * 100 + '%'); });
  n.addEventListener('mouseenter', () => { n.style.setProperty('--ns', 1.07); $('#cur').classList.add('big'); });
  n.addEventListener('mouseleave', () => { n.style.setProperty('--ns', 1); n.style.setProperty('--nrx', '0deg'); n.style.setProperty('--nry', '0deg'); $('#cur').classList.remove('big'); });
  const open = e => { $('#cur').classList.remove('big'); burst(e.clientX, e.clientY); setTimeout(() => location.hash = '#/warnings', 380); };
  n.addEventListener('click', open); img.addEventListener('click', e => { if (scrollY < innerHeight * .3) open(e); });
  // per-frame parallax
  (function f() { const dx = ptr.mx / innerWidth - .5, dy = ptr.my / innerHeight - .5, s = img.style;
    s.setProperty('--ry', dx * 16 + 'deg'); s.setProperty('--rx', -dy * 12 + 'deg'); s.setProperty('--ix', dx * -24 + 'px'); s.setProperty('--iy', dy * -24 + 'px');
    s.setProperty('--px', dx * -36 + 'px'); s.setProperty('--py', dy * -36 + 'px'); s.setProperty('--gx', (dx + .5) * 100 + '%'); s.setProperty('--gy', (dy + .5) * 100 + '%');
    n.style.setProperty('--nx', dx * 36 + 'px'); n.style.setProperty('--ny', dy * 36 + 'px'); requestAnimationFrame(f); })();
  // routes = live tracking (same arcs/slack; adds marker, status, hover, click → drawer)
  const bez = t => [(1 - t) ** 2 * 2 + 2 * (1 - t) * t * 150 + t * t * 298, (1 - t) ** 2 * 28 + 2 * (1 - t) * t * -12 + t * t * 28];
  load($('#routes'), getTracking, list => {
    $('#routes').innerHTML = list.map(s => { const [x, y] = bez(s.progress), c = STATUS[s.status][1];
      return `<div class="rt" data-id="${esc(s.id)}" data-t="${s.progress}" tabindex="0" role="button" aria-label="Track ${esc(s.countryName)} shipment"><div>${esc(s.countryName)}<small>${esc(s.study)} · ${esc(s.origin)} → ${esc(s.destination)}</small></div><div class="arc"><svg viewBox="0 0 300 30" preserveAspectRatio="none"><path d="M2 28 Q150 -12 298 28" stroke="${c}" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/></svg><i class="mk" style="left:${x / 3}%;top:${y / .3}%;--c:${c}"></i><span class="st" style="left:${x / 3}%">${esc(s.statusLabel)}</span></div><div class="sl">${s.slackDays}d</div></div>`; }).join('');
    const u = list[0]?.updatedAt; $('#live').hidden = false; $('#liveu').textContent = u ? new Date(u).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET' : '—';
    $$('.rt').forEach(r => { r.onclick = () => openTracking(r.dataset.id); r.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openTracking(r.dataset.id); } }; });
    onScroll(); mountMap(list); }, { emptyMsg: 'No shipments in the current plan.', label: 'Loading routes' });
  initInventory();
  initCalendar();
  function onScroll() { const lp = clamp(scrollY / innerHeight), H = document.documentElement.scrollHeight - innerHeight, s = img.style;
    document.documentElement.style.setProperty('--p', clamp(scrollY / (H || 1)));
    s.setProperty('--sx', lp * 24 + 'vw'); s.setProperty('--sy', lp * 4 + 'vh'); s.setProperty('--rz', (-14 + clamp(scrollY / (H || 1)) * 120) + 'deg'); s.setProperty('--sc', 1 - lp * .25); s.setProperty('--io', 1 - lp * .94); s.setProperty('--br', 1 - lp * .4);
    document.documentElement.style.setProperty('--no', clamp(1 - lp * 2.5)); n.style.pointerEvents = lp > .3 ? 'none' : 'auto';
    const sec = $('#shipments'), r = sec.getBoundingClientRect(), sp = clamp(-r.top / (r.height - innerHeight || 1));
    $$('.rt').forEach((rt, i) => { const d = clamp(sp * 1.6 - i * .15); rt.querySelector('path').style.strokeDashoffset = 1 - d; rt.classList.toggle('on', d >= +rt.dataset.t); }); }
  addEventListener('scroll', onScroll, { passive: true }); addEventListener('resize', onScroll); onScroll();
  const io = new IntersectionObserver(es => es.forEach(e => e.isIntersecting && e.target.classList.add('in')), { threshold: .3 }); $$('.rv').forEach(e => io.observe(e));
}

/* ---------- calendar (far right) + day drawer ---------- */
const TODAY = '2026-10-17'; // demo "today" matching the mock data; use the real date with a backend
let calMonth = TODAY.slice(0, 7);
const TYPE = { packed: 'Packed', customs: 'Customs', in_transit: 'In transit', delivered: 'Delivered', deadline: 'Deadline', alert: 'Alert', review: 'Review' };
const RISKC = { critical: 'var(--hot)', high: 'var(--hot)', medium: 'var(--warn)', low: 'var(--ok)' };
function initCalendar() {
  $('#drawer-x').onclick = closeDrawer; $('#scrim').onclick = closeDrawer;
  addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#drawer').hidden) { e.stopImmediatePropagation(); closeDrawer(); } }, true);
  const shift = n => { const [y, m] = calMonth.split('-').map(Number), d = new Date(y, m - 1 + n, 1); calMonth = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; drawCal(); };
  $('#calp').onclick = () => shift(-1); $('#caln').onclick = () => shift(1);
  drawCal();
}
function drawCal() {
  const [y, m] = calMonth.split('-').map(Number), first = new Date(y, m - 1, 1), days = new Date(y, m, 0).getDate(), pad = (first.getDay() + 6) % 7;
  $('#calm').textContent = first.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  load($('#calg'), () => getCalendar(calMonth), c => {
    const by = {}; c.events.forEach(e => { (by[e.date] ||= []).push(e); });
    let html = ['M', 'T', 'W', 'T', 'F', 'S', 'S'].map(d => `<span class="dow">${d}</span>`).join('') + '<span></span>'.repeat(pad);
    for (let d = 1; d <= days; d++) { const iso = `${calMonth}-${String(d).padStart(2, '0')}`, ev = by[iso] || [], maj = ev.some(e => e.level === 'major');
      html += `<button class="cd ${iso === TODAY ? 'today' : ''} ${ev.length ? 'has' : ''}" data-d="${iso}" title="${esc(ev.map(e => e.label).join(' · '))}">${d}${ev.length ? `<i class="${maj ? 'maj' : ''}"></i>` : ''}</button>`; }
    $('#calg').innerHTML = html;
    $$('#calg .cd').forEach(b => b.onclick = () => { $$('#calg .cd').forEach(x => x.classList.toggle('sel', x === b)); openDay(b.dataset.d, by[b.dataset.d] || []); });
  }, { label: 'Loading' });
}
async function openDay(date, events) {
  const d = $('#drawer'), body = $('#dbody'), nice = new Date(date + 'T12:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  d.style.setProperty('--c', events.some(e => e.level === 'major') ? 'var(--hot)' : 'rgba(255,255,255,.3)');
  body.innerHTML = `<div class="k">${date === TODAY ? 'Today' : 'Day schedule'}</div><h3>${nice}</h3><div id="dtl"><div class="state"><span class="spin"></span>Loading…</div></div><div id="dai"></div>`;
  d.hidden = false; $('#scrim').hidden = false; requestAnimationFrame(() => document.body.classList.add('drawer-open'));
  getDaySchedule(date).then(s => {
    $('#dtl').innerHTML = s.items.length ? `<div class="dtl">${s.items.map(it => `<div class="ti t-${it.type}"><time>${esc(it.time)}</time><div><span class="tt">${TYPE[it.type] || esc(it.type)}</span><div class="tn">${esc(it.title)}</div><div class="tp">${esc(it.party)} · ${esc(it.shipmentId)} · ${esc(it.status)}</div></div></div>`).join('')}</div>`
      : `<div class="state">${events.length ? esc(events.map(e => e.label).join(' · ')) : 'No shipment milestones on this day.'}</div>`;
  }).catch(e => { $('#dtl').innerHTML = `<div class="state err">Couldn’t load: ${esc(e.message)}</div>`; });
  $('#dai').innerHTML = '<div class="chalk"><div class="state"><span class="spin"></span>Chalk AI is thinking…</div></div>';
  getChalkInsight(date).then(i => {
    $('#dai').innerHTML = `<div class="chalk"><div class="chh"><span class="chb">✦ Powered by Chalk AI</span><span class="risk" style="color:${RISKC[i.risk] || 'var(--mute)'}">${esc(i.risk)} risk</span></div>
      <div class="cht">Chalk AI: risk &amp; recommendations</div><p>${esc(i.summary)}</p>${i.recommendations.length ? `<ul>${i.recommendations.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}<div class="cap">Synthetic demo insight</div></div>`;
  }).catch(e => { $('#dai').innerHTML = `<div class="chalk"><div class="state err">Chalk AI unavailable: ${esc(e.message)}</div></div>`; });
}
function closeDrawer() { document.body.classList.remove('drawer-open'); $$('.rt,.ti2').forEach(x => x.classList.remove('sel')); $$('#calg .cd').forEach(x => x.classList.remove('sel')); setTimeout(() => { $('#drawer').hidden = true; $('#scrim').hidden = true; }, 450); }
function initInventory() {
  const RISK = { blocked: 0, at_risk: 1, on_track: 2, no_shipment: 3 }; let fStudy = 'All', fStat = 'All', sortBy = 'date', items = [], tiles = [];
  $('#invbar').innerHTML = ['All', 'NOVA-24', 'ORION-7', 'HALO-3'].map(x => `<button class="chip ${x === 'All' ? 'on' : ''}" data-st="${x}">${x}</button>`).join('') + '<span class="sep"></span>' +
    [['All', 'Any status'], ['at_risk', 'At risk'], ['blocked', 'Blocked'], ['on_track', 'On track']].map(([k, l]) => `<button class="chip ${k === 'All' ? 'on' : ''}" data-ss="${k}">${l}</button>`).join('') + '<span class="sep"></span>' +
    [['date', 'Next date'], ['risk', 'Risk']].map(([k, l]) => `<button class="chip ${k === 'date' ? 'on' : ''}" data-so="${k}">Sort · ${l}</button>`).join('');
  const grid = $('#grid');
  load(grid, getInventory, list => {
    items = list;
    grid.innerHTML = list.map((t, i) => { const max = Math.max(t.onHand, t.reorderLevel) * 1.2 || 1, d0 = new Date(t.nextShipDate + 'T12:00');
      const next3 = [1, 2, 3].map(k => fmtDate(new Date(+d0 + k * t.cadenceWeeks * 7 * 864e5).toISOString()));
      return `<div class="tile" data-id="${t.id}" style="--i:${i % 12};--fx:${300 - (i % 6) * 60};--fy:-120">
      <div class="top"><span>${esc(t.study)}</span><span class="dot" style="background:${STATUS[t.status][1]}" title="${STATUS[t.status][0]}"></span></div>
      <h4>${esc(t.countryName)}</h4><div class="sub">${esc(t.kit)} · every ${t.cadenceWeeks} wks</div>
      <div class="nx"><span>Next ship</span>${t.status === 'blocked' ? 'On hold' : fmtDate(t.nextShipDate)}</div>
      <div class="stock"><i style="width:${t.onHand / max * 100}%;background:${t.onHand < t.reorderLevel ? 'var(--warn)' : 'var(--ok)'}"></i><b style="left:${t.reorderLevel / max * 100}%"></b></div>
      <div class="units">${t.onHand} on hand · reorder at ${t.reorderLevel}</div>
      <div class="more"><div><small>Last 8 runs</small><div class="runs">${t.runs.map(r => `<i class="${r}"></i>`).join('')}</div><div class="units">${t.runs.filter(r => r === 'on_time').length}/8 on time · ${esc(t.storage)}</div></div>
      <div><small>Next 3 dates</small><ul>${next3.map(d => `<li>${d}</li>`).join('')}</ul></div></div></div>`; }).join('');
    tiles = $$('.tile', grid);
    const tio = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); tio.unobserve(e.target); } }), { threshold: .15 }); tiles.forEach(t => tio.observe(t));
    tiles.forEach(t => { t.addEventListener('mousemove', e => { const r = t.getBoundingClientRect(); t.style.setProperty('--ty', ((e.clientX - r.left) / r.width - .5) * 14 + 'deg'); t.style.setProperty('--tx', -((e.clientY - r.top) / r.height - .5) * 14 + 'deg'); });
      t.addEventListener('click', () => flip(() => { const o = t.classList.contains('open'); tiles.forEach(x => x.classList.remove('open')); if (!o) t.classList.add('open'); })); });
    apply();
  }, { emptyMsg: 'No recurring shipments.', label: 'Loading inventory' });
  function flip(mut) { const f = new Map(tiles.filter(t => !t.classList.contains('gone')).map(t => [t, t.getBoundingClientRect()])); mut();
    tiles.forEach(t => { if (t.classList.contains('gone')) return; const a = f.get(t), b = t.getBoundingClientRect(); t.style.transitionDelay = '0s';
      if (a) t.animate([{ transform: `translate(${a.left - b.left}px,${a.top - b.top}px)` }, { transform: 'none' }], { duration: 650, easing: 'cubic-bezier(.16,1,.3,1)' });
      else { t.classList.add('in'); t.animate([{ opacity: 0, transform: 'scale(.8)' }, { opacity: 1, transform: 'none' }], { duration: 500 }); } }); }
  function apply() { flip(() => { const by = id => items.find(x => x.id === id);
    tiles.forEach(t => { const d = by(t.dataset.id); t.classList.toggle('gone', !((fStudy === 'All' || d.study === fStudy) && (fStat === 'All' || d.status === fStat))); });
    tiles.slice().sort((a, b) => { const x = by(a.dataset.id), y = by(b.dataset.id); return sortBy === 'date' ? x.nextShipDate.localeCompare(y.nextShipDate) : RISK[x.status] - RISK[y.status] || x.onHand / x.reorderLevel - y.onHand / y.reorderLevel; }).forEach(t => grid.appendChild(t)); }); }
  $$('#invbar .chip').forEach(c => c.onclick = () => { const g = c.dataset.st ? 'st' : c.dataset.ss ? 'ss' : 'so'; $$(`#invbar [data-${g}]`).forEach(x => x.classList.toggle('on', x === c));
    if (g === 'st') fStudy = c.dataset.st; if (g === 'ss') fStat = c.dataset.ss; if (g === 'so') sortBy = c.dataset.so; if (tiles.length) apply(); });
}

/* ---------- tracking drawer ---------- */
const MS_ICON = { completed: '✓', current: '●', upcoming: '' };
async function openTracking(id) {
  const d = $('#drawer'), body = $('#dbody');
  $$('.rt').forEach(r => r.classList.toggle('sel', r.dataset.id === id));
  d.hidden = false; $('#scrim').hidden = false; requestAnimationFrame(() => document.body.classList.add('drawer-open'));
  body.innerHTML = '<div class="state"><span class="spin"></span>Loading tracking…</div>';
  try {
    const t = await getTrackingDetail(id), c = STATUS[t.status][1];
    d.style.setProperty('--c', c);
    const tm = s => s ? new Date(s).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET' : '';
    body.innerHTML = `<div class="k">Live tracking · ${esc(t.id.toUpperCase())}</div><h3>${esc(t.countryName)}</h3>
      <p class="dsub">${esc(t.study)} · ${esc(t.kit)}</p>
      <div class="trk-path"><span>${esc(t.origin)}</span><b>${esc(t.currentLocation)}</b><span>${esc(t.destination)}</span><i style="--p:${t.progress * 100}%"></i></div>
      <dl class="trk-kv"><div><dt>ETA</dt><dd>${t.eta ? fmtDate(t.eta) : 'On hold'}</dd></div><div><dt>Target</dt><dd>${fmtDate(t.targetDelivery)}</dd></div><div><dt>Slack</dt><dd style="color:${t.slackDays < 0 ? 'var(--hot)' : t.slackDays === 0 ? 'var(--warn)' : 'var(--ok)'}">${t.slackDays > 0 ? '+' : ''}${t.slackDays}d</dd></div><div><dt>Temp</dt><dd>${t.temperatureC.toFixed(1)} °C <small>${esc(t.tempRange)}</small></dd></div></dl>
      <p class="trk-note">${esc(t.statusLabel)} — ${esc(t.note)}</p>
      <ol class="tl">${t.milestones.map(m => `<li class="${m.state}"><i>${MS_ICON[m.state]}</i><div><b>${esc(m.label)}</b><small>${m.state === 'upcoming' ? 'Upcoming' : m.state === 'current' ? 'Current · ' + tm(m.at) : tm(m.at)}</small></div></li>`).join('')}</ol>
      <p class="syn">Synthetic demo data · updated ${tm(t.updatedAt)}</p>`;
  } catch (err) { body.innerHTML = `<div class="state err">Couldn’t load tracking: ${esc(err.message)}</div>`; }
}

/* ---------- Google Maps tracking (JS API when the key works, else keyless embed + overlay) ---------- */
const tlistHtml = list => list.map(s => `<button class="ti2" role="listitem" data-id="${esc(s.id)}" style="--c:${STATUS[s.status][1]}"><i></i><span><b>${esc(s.countryName)}</b><small>${esc(s.statusLabel)}</small></span><em>${s.slackDays}d</em></button>`).join('');
function mountMap(list) {
  let mode = null; // 'js' | 'embed'
  const toEmbed = () => { if (mode === 'embed') return; mode = 'embed'; embedMap(list); };
  document.addEventListener('gmaps-auth-failure', toEmbed, { once: true });
  loadGoogleMaps().then(g => {
    if (mode) return;
    mode = 'js';
    const css = getComputedStyle(document.documentElement), color = s => css.getPropertyValue(STATUS[s.status][1].slice(4, -1)).trim() || '#fff';
    $('#routes').hidden = true; $('#gmap').hidden = false;
    let m;
    const pick = id => { m.select(id); $$('#tlist .ti2').forEach(x => x.classList.toggle('sel', x.dataset.id === id)); openTracking(id); };
    m = buildMap(g, $('#map'), list, color, pick);
    $('#tlist').innerHTML = tlistHtml(list);
    $$('#tlist .ti2').forEach(b => b.onclick = () => pick(b.dataset.id));
    attachLiveShipments();
    new IntersectionObserver((es, o) => es.forEach(e => { if (e.isIntersecting) { m.draw(); o.disconnect(); } }), { threshold: .25 }).observe($('#gmap'));
  }).catch(toEmbed);
}

/* ---------- keyless Google Maps embed with the routes drawn on top (approximate overlay) ---------- */
function embedMap(list) {
  const css = getComputedStyle(document.documentElement), color = s => css.getPropertyValue(STATUS[s.status][1].slice(4, -1)).trim() || '#fff';
  $('#routes').hidden = true; $('#gmap').hidden = false;
  const el = $('#map'); el.innerHTML = '';
  let sel = null;
  const routes = list.filter(s => s.coords).map(s => ({ s, c: color(s), path: greatCircle(s.coords.origin, s.coords.destination) }));
  const ptsFor = id => { const r = routes.find(x => x.s.id === id); return r ? [...r.path, r.s.coords.current] : routes.flatMap(x => x.path); };
  const pathD = (P, pts) => pts.map((p, i) => (i ? 'L' : 'M') + P(p).map(v => v.toFixed(1)).join(' ')).join('');
  const view = mountEmbed(el, { title: 'Google Map of shipments', note: 'Google Maps · approximate overlay',
    render: P => routes.map(({ s, c, path }) => { const on = !sel || sel === s.id, [cx, cy] = P(s.coords.current), [ox, oy] = P(s.coords.origin), [dx, dy] = P(s.coords.destination);
      return `<g class="eroute${sel === s.id ? ' sel' : ''}" data-id="${esc(s.id)}" style="opacity:${on ? 1 : .35}"><title>${esc(s.countryName)} · ${esc(s.id)}</title>
        <path d="${pathD(P, path)}" class="ehit"/><path d="${pathD(P, path)}" stroke="${c}" stroke-width="${sel === s.id ? 3.5 : 2}" fill="none"/>
        <circle cx="${ox}" cy="${oy}" r="4" fill="#0b0b0f" stroke="${c}" stroke-width="2"/><circle cx="${dx}" cy="${dy}" r="4" fill="#0b0b0f" stroke="${c}" stroke-width="2"/>
        <circle cx="${cx}" cy="${cy}" r="9" fill="none" stroke="${c}" stroke-width="1.5" class="epulse"/><circle cx="${cx}" cy="${cy}" r="3.5" fill="${c}"/></g>`; }).join(''),
    bind: svg => svg.querySelectorAll('.eroute').forEach(g => g.addEventListener('click', () => pick(g.dataset.id))) });
  function pick(id) { sel = id; view.setView(ptsFor(id)); $$('#tlist .ti2').forEach(x => x.classList.toggle('sel', x.dataset.id === id)); openTracking(id); }
  view.setView(ptsFor(null));
  $('#tlist').innerHTML = tlistHtml(list);
  $$('#tlist .ti2').forEach(b => b.onclick = () => pick(b.dataset.id));
  attachLiveShipments();
}
