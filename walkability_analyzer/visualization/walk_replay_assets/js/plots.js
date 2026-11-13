// ---------------------------------------------------------------- synced time-series plots (shared view, playhead, hover, zoom, seek)
const yMax = (k, floor, q = 99, pad = 1.15) => Math.max(floor, (pct(SIG[k], q) ?? floor) * pad);
const TH_ = CFG.thresholds || {};
const PLOTS = {
  speed: { title: 'GPS speed [m/s]', y: [0, yMax('speed_gps', 2)],
    series: [['speed_gps', '#4cc2ff', 'GPS speed', 1], ['speed_med', '#3fd07a', `${TH_.speed_median_window_s ?? 2} s median`, 1.8]],
    lines: [[SUM.baseline_speed, 'baseline'], [ok(SUM.segment_mean_speed) && TH_.slowdown_rel ? TH_.slowdown_rel * SUM.segment_mean_speed : null, `slowdown ≤ ${TH_.slowdown_rel} v̄`],
      [TH_.stop_speed, `stop < ${TH_.stop_speed} m/s`]], bands: ['stop', 'slowdown', 'gps_artifact'] },
  cadence: { title: `Candidate step rate [steps/min, ${TH_.cadence_window_s ?? 5} s] + step events`, y: [0, yMax('cadence', 140, 99, 1.1)],
    series: [['cadence', '#f2b33d', 'step rate', 1.3]], lines: [[SUM.baseline_cadence, 'baseline'], [SUM.spectral_cadence, 'spectral']], bands: ['stop', 'change'], steps: true },
  acc: { title: 'RMS of band-passed vertical acceleration aᵥ [m/s², 1 s]', y: [0, yMax('acc_rms', 1, 99, 1.2)],
    series: [['acc_rms', '#e05cff', 'RMS aᵥ', 1.3]], lines: [], bands: ['stop', 'slowdown', 'change'] },
  hr: { title: 'Heart rate [bpm] (Polar, start-time aligned)', y: HAS_HR ? [Math.floor((pct(SIG.hr, 1) - 5) / 5) * 5, Math.ceil((Math.max(pct(SIG.hr, 99), SUM.hr_threshold || 0) + 5) / 5) * 5] : [60, 140],
    series: [['hr', '#ff5c5c', 'HR', 1.3]], lines: [[SUM.hr_baseline, 'baseline'], [SUM.hr_threshold, 'spike thr.']], bands: ['hr_spike'],
    empty: HAS_HR ? null : 'no heart-rate data for this recording' },
  owi: { title: 'OWI per window', y: [0, 100], win: ['owi'], lines: [[CFG.poor_threshold, `poor < ${CFG.poor_threshold}`]], bands: ['stop', 'slowdown'],
    empty: HAS_OWI ? null : 'no per-window scores' },
  mods: { title: 'Modules per window [0–100]', y: [0, 100], win: MOD_KEYS.filter(k => MOD_AVAIL[k]), lines: [], bands: [],
    empty: HAS_OWI ? null : 'no per-window scores' } };
if (SIG.rmssd && SIG.rmssd.some(ok)) PLOTS.hr.series.push(['rmssd', '#3fd07a', 'RMSSD [ms]', 1]);
const MODC = { msi: '#4cc2ff', eei: '#b06cff', pci: '#ff5c5c' };
const plotCanvases = [...document.querySelectorAll('[data-plot]')];

function drawPlot(cv) {
  const P = PLOTS[cv.dataset.plot], { c, w, h } = fit(cv), L = 38, R = 8, T = 18, B = 16, pw = w - L - R, ph = h - T - B, { t0, t1 } = S.view;
  cv._g = { L, pw }; const X = t => L + (t - t0) / (t1 - t0) * pw, Y = v => T + ph - (v - P.y[0]) / (P.y[1] - P.y[0]) * ph;
  c.fillStyle = TH.panel; c.fillRect(0, 0, w, h); c.font = '10px Consolas'; c.lineWidth = 1;
  for (let k = 0; k <= 4; k++) { const v = P.y[0] + k * (P.y[1] - P.y[0]) / 4, y = Y(v); c.strokeStyle = TH.grid; c.beginPath(); c.moveTo(L, y); c.lineTo(L + pw, y); c.stroke();
    c.fillStyle = TH.dim; c.textAlign = 'right'; c.fillText(+v.toFixed(1), L - 4, y + 3); }
  const st = niceStep(t1 - t0, pw / 70); c.textAlign = 'center';
  for (let tt = Math.ceil(t0 / st) * st; tt <= t1; tt += st) { const x = X(tt); c.strokeStyle = TH.grid; c.beginPath(); c.moveTo(x, T); c.lineTo(x, T + ph); c.stroke(); c.fillText(+tt.toFixed(1), x, h - 4); }
  c.textAlign = 'left'; c.save(); c.beginPath(); c.rect(L, T, pw, ph); c.clip();
  DATA.events.forEach(e => { if (!P.bands.includes(e.type) || e.t1 < t0 || e.t0 > t1) return; c.fillStyle = hexA(EV[e.type].c, .16); c.fillRect(X(e.t0), T, X(e.t1) - X(e.t0), ph); });
  P.lines.forEach(([v, n]) => { if (!ok(v)) return; c.strokeStyle = TH.dim; c.setLineDash([4, 4]); c.beginPath(); c.moveTo(L, Y(v)); c.lineTo(L + pw, Y(v)); c.stroke(); c.setLineDash([]);
    c.fillStyle = TH.dim; c.fillText(n, L + pw - c.measureText(n).width - 3, Y(v) - 3); });
  if (P.series) { const ts = SIG.t, i0 = Math.max(0, bsearch(ts, t0) - 1), i1 = Math.min(ts.length - 1, bsearch(ts, t1) + 1), stp = Math.max(1, Math.floor((i1 - i0) / (pw * 1.5)));
    P.series.forEach(([k, col, , lw]) => { const ys = SIG[k]; if (!ys) return; c.strokeStyle = col; c.lineWidth = lw || 1.3; c.beginPath(); let pen = false;
      for (let i = i0; i <= i1; i += stp) { const v = ys[i]; if (!ok(v)) { pen = false; continue; } pen ? c.lineTo(X(ts[i]), Y(v)) : c.moveTo(X(ts[i]), Y(v)); pen = true; } c.stroke(); }); }
  if (P.steps && (t1 - t0) < 240) { c.strokeStyle = hexA('#f2b33d', .7); c.lineWidth = 1; c.beginPath(); DATA.steps_t.forEach(s => { if (s >= t0 && s <= t1) { c.moveTo(X(s), T + ph); c.lineTo(X(s), T + ph - 7); } }); c.stroke(); }
  if (P.win) P.win.forEach(k => { WINS.forEach((wn, j) => { const a = WIN_C[j] - WSTEP / 2, b = WIN_C[j] + WSTEP / 2, v = wn[k]; if (b < t0 || a > t1 || !ok(v)) return;
      if (k === 'owi') { c.fillStyle = scoreColor(v); c.globalAlpha = .8; c.fillRect(X(a), Y(v), Math.max(1, X(b) - X(a) - .5), Y(0) - Y(v)); c.globalAlpha = 1; }
      else { c.strokeStyle = MODC[k]; c.lineWidth = 1.5; c.beginPath(); c.moveTo(X(a), Y(v)); c.lineTo(X(b), Y(v)); c.stroke(); } }); });
  c.restore();
  if (P.empty) { c.fillStyle = TH.dim; c.font = 'italic 12px Segoe UI'; c.textAlign = 'center'; c.fillText(P.empty, L + pw / 2, T + ph / 2); c.textAlign = 'left'; }
  if (S.hoverT != null && S.hoverT >= t0 && S.hoverT <= t1) { c.strokeStyle = TH.dim; c.setLineDash([2, 3]); c.beginPath(); c.moveTo(X(S.hoverT), T); c.lineTo(X(S.hoverT), T + ph); c.stroke(); c.setLineDash([]); }
  if (S.t >= t0 && S.t <= t1) { c.strokeStyle = TH.acc; c.lineWidth = 2; c.beginPath(); c.moveTo(X(S.t), T - 2); c.lineTo(X(S.t), T + ph); c.stroke(); c.lineWidth = 1; }
  c.strokeStyle = TH.line; c.strokeRect(L + .5, T + .5, pw, ph);
  c.font = '600 11px Segoe UI'; c.fillStyle = TH.fg; c.fillText(P.title, L, 12); let lx = L + c.measureText(P.title).width + 12; c.font = '10px Segoe UI';
  (P.series || (P.win.length > 1 ? P.win.map(k => [k, MODC[k], k.toUpperCase()]) : [])).forEach(([, col, n]) => { c.fillStyle = col; c.fillRect(lx, 6, 10, 3); c.fillStyle = TH.dim; c.fillText(n, lx + 13, 11); lx += c.measureText(n).width + 24; }); }

function tipHtml(t) { const W = winAt(t), act = activeEvents(t).filter(e => e.type !== 'video');
  return `<b>t = ${t.toFixed(1)} s</b> (+${fmtT(t - T0)})<br>GPS speed ${f2(sigAt('speed_gps', t))} · median ${f2(sigAt('speed_med', t))} m/s<br>step rate ${f0(sigAt('cadence', t))} spm · RMS aᵥ ${f2(sigAt('acc_rms', t))}` +
    (HAS_HR ? `<br>HR ${f0(sigAt('hr', t))} bpm` : '') +
    (W ? `<br>OWI <span style="color:${scoreColor(W.owi)}">${f1(W.owi)}</span> · MSI ${f1(W.msi)} · EEI ${f1(W.eei)} · PCI ${f1(W.pci)}` : '') +
    act.map(e => `<br><span style="color:${EV[e.type].c}">■ ${EV[e.type].n}</span>`).join(''); }
// shared time navigation for every time-axis canvas
function attachTimeNav(cv, onClick) { let drag = null; const tip = $('#tip');
  const tAt = x => { const g = cv._g || { L: 0, pw: cv.clientWidth }; return S.view.t0 + clamp((x - g.L) / g.pw, 0, 1) * (S.view.t1 - S.view.t0); };
  cv.addEventListener('mousedown', e => drag = { x: e.clientX, t0: S.view.t0, t1: S.view.t1, moved: false });
  window.addEventListener('mousemove', e => { if (!drag) return; const dx = e.clientX - drag.x; if (Math.abs(dx) > 3) drag.moved = true;
    if (drag.moved) { const dt = -dx / cv._g.pw * (drag.t1 - drag.t0); setView(drag.t0 + dt, drag.t1 + dt); } });
  window.addEventListener('mouseup', e => { if (drag && !drag.moved && e.target === cv) { if (!onClick || !onClick(e, tAt(e.offsetX))) seek(tAt(e.offsetX)); } drag = null; });
  cv.addEventListener('mousemove', e => { S.hoverT = tAt(e.offsetX); S.dirty = true; if (cv.dataset.plot) { tip.style.display = 'block'; tip.innerHTML = tipHtml(S.hoverT);
      const r = tip.getBoundingClientRect(); tip.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 6) + 'px'; tip.style.top = Math.max(4, e.clientY - r.height - 10) + 'px'; } });
  cv.addEventListener('mouseleave', () => { S.hoverT = null; tip.style.display = 'none'; S.dirty = true; });
  cv.addEventListener('wheel', e => { e.preventDefault(); const tm = tAt(e.offsetX), z = e.deltaY < 0 ? 1 / 1.25 : 1.25;
    setView(tm - (tm - S.view.t0) * z, tm + (S.view.t1 - tm) * z); }, { passive: false });
  cv.addEventListener('dblclick', () => setView(T0, T1)); }
plotCanvases.forEach(cv => attachTimeNav(cv));

// ---- score sparkline under the video
const cvSpark = $('#cvSpark');
function drawSpark() { const { c, w, h } = fit(cvSpark), X = t => (t - T0) / D * w; c.fillStyle = TH.panel2; c.fillRect(0, 0, w, h);
  WINS.forEach((wn, k) => { if (!ok(wn.owi)) return; const x0 = X(WIN_C[k] - WSTEP / 2), x1 = X(WIN_C[k] + WSTEP / 2), y = h - 3 - wn.owi / 100 * (h - 6);
    c.fillStyle = scoreColor(wn.owi); c.globalAlpha = .85; c.fillRect(x0, y, Math.max(1, x1 - x0), h - 3 - y); });
  c.globalAlpha = 1; c.strokeStyle = TH.dim; c.setLineDash([3, 3]); const yp = h - 3 - (CFG.poor_threshold || 35) / 100 * (h - 6); c.beginPath(); c.moveTo(0, yp); c.lineTo(w, yp); c.stroke(); c.setLineDash([]);
  c.fillStyle = hexA('#4cc2ff', .25); c.fillRect(X(S.view.t0), 0, X(S.view.t1) - X(S.view.t0), 2);
  c.strokeStyle = TH.acc; c.lineWidth = 2; c.beginPath(); c.moveTo(X(S.t), 0); c.lineTo(X(S.t), h); c.stroke(); c.lineWidth = 1;
  c.fillStyle = TH.dim; c.font = '10px Consolas'; c.fillText(HAS_OWI ? 'OWI / window' : 'no window scores', 4, 10); }
cvSpark.addEventListener('click', e => seek(T0 + e.offsetX / cvSpark.clientWidth * D));
