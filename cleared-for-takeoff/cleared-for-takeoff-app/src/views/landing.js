import { $, $$, esc, STATUS, fmtDate, load, burst } from '../ui.js';
import { getShipments, getInventory, getWarnings } from '../api.js';
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
  // routes
  load($('#routes'), getShipments, list => {
    $('#routes').innerHTML = list.map(s => `<div class="rt"><div>${esc(s.countryName)}<small>${esc(s.study)} · ${esc(s.origin)} → ${esc(s.destination)}</small></div><svg viewBox="0 0 300 30" preserveAspectRatio="none"><path d="M2 28 Q150 -12 298 28" stroke="${STATUS[s.status][1]}" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/></svg><div class="sl">${s.slackDays}d</div></div>`).join('');
    onScroll(); }, { emptyMsg: 'No shipments in the current plan.', label: 'Loading routes' });
  initInventory();
  function onScroll() { const lp = clamp(scrollY / innerHeight), H = document.documentElement.scrollHeight - innerHeight, s = img.style;
    document.documentElement.style.setProperty('--p', clamp(scrollY / (H || 1)));
    s.setProperty('--sx', lp * 24 + 'vw'); s.setProperty('--sy', lp * 4 + 'vh'); s.setProperty('--rz', (-14 + clamp(scrollY / (H || 1)) * 120) + 'deg'); s.setProperty('--sc', 1 - lp * .25); s.setProperty('--io', 1 - lp * .94); s.setProperty('--br', 1 - lp * .4);
    document.documentElement.style.setProperty('--no', clamp(1 - lp * 2.5)); n.style.pointerEvents = lp > .3 ? 'none' : 'auto';
    const sec = $('#shipments'), r = sec.getBoundingClientRect(), sp = clamp(-r.top / (r.height - innerHeight || 1));
    $$('.rt path').forEach((p, i) => p.style.strokeDashoffset = 1 - clamp(sp * 1.6 - i * .15)); }
  addEventListener('scroll', onScroll, { passive: true }); addEventListener('resize', onScroll); onScroll();
  const io = new IntersectionObserver(es => es.forEach(e => e.isIntersecting && e.target.classList.add('in')), { threshold: .3 }); $$('.rv').forEach(e => io.observe(e));
}
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
