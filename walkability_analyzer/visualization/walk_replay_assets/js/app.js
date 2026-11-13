// ---------------------------------------------------------------- app controller: render loop, transport, keyboard, export, deep links
const TABS = ['plots', 'timeline', 'log', 'score', 'phys', 'config', 'summary'];
function wallClock(t) { if (!META.wallclock0) return ''; const d = new Date(new Date(META.wallclock0).getTime() + t * 1000);
  return isNaN(d) ? '' : d.toTimeString().slice(0, 8); }
function render() {
  const W = winAt(S.t), wc = wallClock(S.t);
  $('#clock').innerHTML = `t = ${S.t.toFixed(1).padStart(6, ' ')} s <small>+${fmtT(S.t - T0)} / ${fmtT(D)}${wc ? ' · ' + wc : ''}${W ? ' · win ' + W.i : ''}</small>`;
  drawHud(); drawThumb(); drawSpark(); drawMap(); updateStatus();
  if (S.tab === 'plots') plotCanvases.forEach(drawPlot);
  if (S.tab === 'timeline') drawTimeline();
  if (S.tab === 'score') drawHist();
  updateLogCursor();
}
let last = performance.now();
function loop(now) { const dt = Math.min(.1, (now - last) / 1000); last = now;
  if (S.playing) {
    const vt = VID.clock();
    if (vt != null) S.t = vt;
    else { S.t += dt * S.rate; if (VID.synced && VID.ready && inVideo(S.t)) VID.play(); }
    if (S.t >= T1) { S.t = T1; setPlaying(false); }
    const { t0, t1 } = S.view; if (S.t > t1 - (t1 - t0) * .02 || S.t < t0) setView(S.t - (t1 - t0) * .1, S.t + (t1 - t0) * .9);
    S.dirty = true; }
  if (S.dirty) { S.dirty = false; try { render(); } catch (err) { console.error(err); } }
  requestAnimationFrame(loop); }
function setPlaying(p) { S.playing = p; if (p && S.t >= T1) seek(T0); $('#bPlay').textContent = p ? '⏸' : '▶'; p ? VID.play() : VID.pause(); S.dirty = true; }
function jumpEvent(dir) { const evs = DATA.events.filter(e => e.type !== 'video' && LOGF.has(e.type)).map(e => Math.max(T0, e.t0)).sort((a, b) => a - b);
  const n = dir > 0 ? evs.find(x => x > S.t + .05) : [...evs].reverse().find(x => x < S.t - .5); if (n != null) seek(n); }
function setTab(name) { S.tab = name; document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.id === 'tab-' + name)); S.logCur = null; S.dirty = true; }
$('#tabs').addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (b) setTab(b.dataset.tab); });
$('#bPlay').onclick = () => setPlaying(!S.playing);
$('#bBack1').onclick = () => seek(S.t - 1); $('#bFwd1').onclick = () => seek(S.t + 1);
$('#bBack10').onclick = () => seek(S.t - 10); $('#bFwd10').onclick = () => seek(S.t + 10);
$('#bPrevEv').onclick = () => jumpEvent(-1); $('#bNextEv').onclick = () => jumpEvent(1);
$('#selRate').onchange = e => { S.rate = +e.target.value; if (VID.master) video.playbackRate = Math.min(16, S.rate); };
function toggleTheme() { document.documentElement.classList.toggle('light'); refreshTheme(); S.dirty = true; }
$('#bTheme').onclick = toggleTheme;

// ---- export
function windowsCsv() { const keys = [...new Set(WINS.flatMap(w => Object.keys(w.metrics || {})))], raws = [...new Set(WINS.flatMap(w => Object.keys(w.raw || {})))];
  return ['window,t0,t1,owi,msi,eei,pci,' + keys.join(',') + ',' + raws.join(',')].concat(WINS.map(w =>
    [w.i, w.t0, w.t1, w.owi, w.msi, w.eei, w.pci, ...keys.map(k => w.metrics?.[k]), ...raws.map(k => w.raw?.[k])].map(csvCell).join(','))).join('\n'); }
function withPlotsDrawn(fn, light) { const prevTab = S.tab, wasLight = document.documentElement.classList.contains('light');
  if (prevTab !== 'plots') setTab('plots');
  if (light && !wasLight) { document.documentElement.classList.add('light'); refreshTheme(); }
  plotCanvases.forEach(drawPlot); const out = fn();
  if (light && !wasLight) { document.documentElement.classList.remove('light'); refreshTheme(); }
  if (prevTab !== 'plots') setTab(prevTab); S.dirty = true; return out; }
function plotsPng() { withPlotsDrawn(() => { const cw = plotCanvases[0].width, ch = plotCanvases[0].height, out = document.createElement('canvas');
  out.width = cw * 3; out.height = ch * 2; const c = out.getContext('2d'); c.fillStyle = TH.panel; c.fillRect(0, 0, out.width, out.height);
  plotCanvases.forEach((cv, i) => c.drawImage(cv, (i % 3) * cw, Math.floor(i / 3) * ch, cw, ch));
  out.toBlob(b => download(`${META.recording_id}_plots_t${S.t.toFixed(0)}.png`, b)); }); }
function printSummary() { setTab('summary'); buildSummary(); withPlotsDrawn(snapPlots, true); setTab('summary'); setTimeout(() => window.print(), 50); }
function linkHere() { const url = location.href.split('#')[0] + `#tab=${S.tab}&t=${S.t.toFixed(1)}`; history.replaceState(null, '', url);
  if (navigator.clipboard) navigator.clipboard.writeText(url).catch(() => {}); }
$('#bExport').onclick = e => { e.stopPropagation(); $('#exportMenu').classList.toggle('open'); };
document.addEventListener('click', () => $('#exportMenu').classList.remove('open'));
$('#exportMenu').addEventListener('click', e => { const k = e.target.dataset.exp; if (!k) return;
  if (k === 'csv') download(`${META.recording_id}_windows.csv`, new Blob([windowsCsv()], { type: 'text/csv' }));
  if (k === 'events') download(`${META.recording_id}_events.csv`, new Blob([eventsCsv()], { type: 'text/csv' }));
  if (k === 'png') plotsPng(); if (k === 'print') printSummary(); if (k === 'link') linkHere(); });
window.addEventListener('beforeprint', () => { if (!$('#snaps')?.children.length) withPlotsDrawn(snapPlots, true); });

// ---- keyboard
window.addEventListener('keydown', e => { if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;
  if (e.code === 'Space') { e.preventDefault(); setPlaying(!S.playing); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); seek(S.t - (e.shiftKey ? 10 : 1)); } else if (e.key === 'ArrowRight') { e.preventDefault(); seek(S.t + (e.shiftKey ? 10 : 1)); }
  else if (e.key === '[') jumpEvent(-1); else if (e.key === ']') jumpEvent(1);
  else if (e.key === 'Home') seek(T0); else if (e.key === 'End') seek(T1);
  else if (e.key >= '1' && e.key <= '7') setTab(TABS[+e.key - 1]); else if (e.key.toLowerCase() === 't') toggleTheme();
  else if (e.key.toLowerCase() === 'f') { const el = $('#vidwrap'); document.fullscreenElement ? document.exitFullscreen() : el.requestFullscreen?.(); } });
window.addEventListener('resize', () => { MAPS.k = null; MAPS.leaflet?.map.invalidateSize(); S.dirty = true; });

// ---- init
$('#metaLine').textContent = `${META.location || ''} · route ${META.route_id} · rec ${META.recording_id} · ${META.fs_hz} Hz · analysed ${META.analysis_date}`;
$('#vidSync').textContent = !GP.available ? 'no video' : VID.synced ? `sync: stomp-clap, Δ = ${VID.delta.toFixed(2)} s (t_v = t + Δ)${GP.sync.suspect ? ' — SUSPECT, verify visually' : ''}${GP.proxy ? ' · H.264 proxy' : ''}` : 'NOT synchronized';
refreshTheme(); initVideo(); initMap(); buildStatus(); buildLog(); buildScore(); buildPhys(); buildConfig(); buildSummary();
setView(T0, Math.min(T1, T0 + Math.max(60, Math.min(180, D))));
// deep link: report.html#tab=timeline&t=320
(() => { const q = new URLSearchParams(location.hash.slice(1)); if (TABS.includes(q.get('tab'))) setTab(q.get('tab')); if (q.has('t')) seek(+q.get('t')); else seek(T0); })();
requestAnimationFrame(loop);
