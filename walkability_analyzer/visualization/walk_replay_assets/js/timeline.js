// ---------------------------------------------------------------- timeline (Gantt of sources, events, windows, thumbnails)
const cvTl = $('#cvTl');
function runs(ts, ys) { const out = []; let a = null; for (let i = 0; i < ts.length; i++) { const on = ok(ys[i]);
  if (on && a == null) a = ts[i]; if (!on && a != null) { out.push([a, ts[i - 1]]); a = null; } } if (a != null) out.push([a, ts[ts.length - 1]]); return out; }
const LANES = (() => { const L = [], G = '#3fd07a';
  const ev = ty => DATA.events.filter(e => e.type === ty).map(e => ({ t0: e.t0, t1: e.t1, col: EV[ty].c, info: `${EV[ty].n}: ${e.label}`, ev: e }));
  const ga = DATA.events.filter(e => e.type === 'gps_artifact').sort((a, b) => a.t0 - b.t0), gpsOk = []; let cur = T0;
  ga.forEach(e => { if (e.t0 > cur) gpsOk.push({ t0: cur, t1: e.t0 }); cur = Math.max(cur, e.t1); }); if (cur < T1) gpsOk.push({ t0: cur, t1: T1 });
  L.push({ g: 'SOURCES', n: `iPhone IMU ${f0(SRC.imu.fs_hz)} Hz`, items: SRC.imu.available ? [{ t0: T0, t1: T1, col: SRC.imu.fs_hz < 50 ? '#f2b33d' : G, info: `IMU ${f0(SRC.imu.fs_hz)} Hz, coverage ${f0(100 * (SRC.imu.coverage ?? 1))} %` }] : [], empty: SRC.imu.available ? null : 'missing' });
  L.push({ n: 'iPhone GPS fix', items: SRC.gps.available ? gpsOk.map(r => ({ ...r, col: G, info: 'GPS: no speed artefact detected' })).concat(ga.map(e => ({ t0: e.t0, t1: e.t1, col: '#f2b33d', info: 'GPS degraded: ' + e.label }))) : [], empty: SRC.gps.available ? null : 'no GPS' });
  const p = SRC.polar;
  L.push({ n: `Polar HR${p.available ? ` (${p.sync.method})` : ''}`, items: HAS_HR ? runs(SIG.t, SIG.hr).map(([a, b]) => ({ t0: a, t1: b, col: p.simulated ? '#f2b33d' : G, info: `Polar ${p.file}: ${p.sync.method} alignment, offset ${f1(p.sync.offset_s)} s${p.simulated ? ' — SIMULATED' : ''}` })) : [], empty: HAS_HR ? null : 'no heart-rate data' });
  L.push({ n: 'Polar RR / HRV', items: p.hrv && SIG.rmssd ? runs(SIG.t, SIG.rmssd).map(([a, b]) => ({ t0: a, t1: b, col: G, info: 'RMSSD available' })) : [], empty: p.hrv ? null : (p.available ? 'not in export → reduced PCI' : 'no Polar file') });
  const g = SRC.gopro;
  const gcov = g.available && VID.synced ? [{ t0: Math.max(T0, -VID.delta), t1: Math.min(T1, (g.duration_s || 0) - VID.delta), col: G, info: `GoPro ${g.file}: stomp-clap Δ = ${VID.delta.toFixed(2)} s${g.proxy ? ' (H.264 proxy)' : ''}` }].filter(r => r.t1 > r.t0) : [];
  L.push({ n: g.available ? `GoPro (Δ ${VID.synced ? VID.delta.toFixed(1) + ' s' : 'n/a'})` : 'GoPro', items: gcov, empty: !g.available ? 'no video' : VID.synced ? null : 'not synchronized' });
  if (THUMBS && VID.synced) L.push({ n: 'GoPro frames', thumbs: true, items: [], h: 2.4 });
  let first = true; for (const ty of Object.keys(EV)) { L.push({ g: first ? 'EVENTS' : null, n: EV[ty].n, items: ev(ty) }); first = false; }
  if (WINS.length) { L.push({ g: 'SCORE', n: 'OWI windows', items: WINS.map((w, j) => ({ t0: WIN_C[j] - WSTEP / 2, t1: WIN_C[j] + WSTEP / 2, col: scoreColor(w.owi), info: `window ${w.i}: ${w.t0}–${w.t1} s  OWI ${f1(w.owi)}  MSI ${f1(w.msi)}  EEI ${f1(w.eei)}  PCI ${f1(w.pci)}` })) });
    for (const k of MOD_KEYS) L.push({ n: k.toUpperCase(), items: MOD_AVAIL[k] ? WINS.map((w, j) => ({ t0: WIN_C[j] - WSTEP / 2, t1: WIN_C[j] + WSTEP / 2, col: scoreColor(w[k]), info: `${k.toUpperCase()} ${f1(w[k])} (window ${w.i})` })) : [], empty: MOD_AVAIL[k] ? null : 'module not used' }); }
  return L; })();
function drawTimeline() { const { c, w, h } = fit(cvTl), L = 160, R = 8, T = 18, pw = w - L - R, { t0, t1 } = S.view, X = t => L + (t - t0) / (t1 - t0) * pw;
  cvTl._g = { L, pw }; c.fillStyle = TH.panel; c.fillRect(0, 0, w, h);
  const units = LANES.reduce((s, l) => s + (l.h || 1), 0), extra = LANES.filter(l => l.g).length * 6, lh = Math.max(11, Math.min(22, (h - T - 6 - extra) / units)); let y = T; cvTl._rows = [];
  const st = niceStep(t1 - t0, pw / 80); c.font = '10px Consolas'; c.textAlign = 'center';
  for (let tt = Math.ceil(t0 / st) * st; tt <= t1; tt += st) { c.strokeStyle = TH.grid; c.beginPath(); c.moveTo(X(tt), T); c.lineTo(X(tt), h); c.stroke(); c.fillStyle = TH.dim; c.fillText(+tt.toFixed(1) + ' s', X(tt), 11); }
  c.textAlign = 'left';
  LANES.forEach(l => { const hh = lh * (l.h || 1); if (l.g) { y += 6; c.fillStyle = TH.acc; c.font = '600 9px Segoe UI'; c.fillText(l.g, 4, y + 2); }
    c.fillStyle = TH.dim; c.font = '11px Segoe UI'; c.fillText(l.n, 14, y + Math.min(hh, lh) * .7);
    c.save(); c.beginPath(); c.rect(L, y, pw, hh); c.clip(); c.fillStyle = TH.panel2; c.fillRect(L, y + 1, pw, hh - 2);
    if (l.empty) { c.fillStyle = TH.bad; c.font = 'italic 10px Segoe UI'; c.fillText(l.empty, L + 6, y + lh * .7); }
    if (l.thumbs && THUMB_IMG && THUMB_IMG.complete) { const th = hh - 4, tw = th * THUMBS.w / THUMBS.h; let lastX = -1e9;
      THUMBS.t.forEach((tvk, k) => { const x = X(tvk - VID.delta); if (x < L - tw || x > L + pw || x - lastX < tw + 1) return; lastX = x;
        c.drawImage(THUMB_IMG, (k % THUMBS.cols) * THUMBS.w, Math.floor(k / THUMBS.cols) * THUMBS.h, THUMBS.w, THUMBS.h, x - tw / 2, y + 2, tw, th); }); }
    l.items.forEach(it => { if (it.t1 < t0 || it.t0 > t1) return; c.fillStyle = it.col; c.globalAlpha = .85; c.fillRect(X(it.t0), y + 3, Math.max(2, X(it.t1) - X(it.t0) - .5), hh - 6); });
    c.globalAlpha = 1; c.restore(); cvTl._rows.push({ y, h: hh, l }); y += hh; });
  if (S.hoverT != null) { c.strokeStyle = TH.dim; c.setLineDash([2, 3]); c.beginPath(); c.moveTo(X(S.hoverT), T); c.lineTo(X(S.hoverT), y); c.stroke(); c.setLineDash([]); }
  if (S.t >= t0 && S.t <= t1) { c.strokeStyle = TH.acc; c.lineWidth = 2; c.beginPath(); c.moveTo(X(S.t), T - 4); c.lineTo(X(S.t), y); c.stroke(); c.lineWidth = 1;
    c.fillStyle = TH.acc; c.beginPath(); c.moveTo(X(S.t) - 5, T - 6); c.lineTo(X(S.t) + 5, T - 6); c.lineTo(X(S.t), T); c.fill(); } }
attachTimeNav(cvTl, (e, t) => { const row = (cvTl._rows || []).find(r => e.offsetY >= r.y && e.offsetY < r.y + r.h); if (!row) return false;
  const it = row.l.items.find(i => t >= i.t0 && t <= i.t1); if (!it) return false;
  $('#tlInfo').innerHTML = `<span class="dot" style="background:${it.col}"></span>${esc(it.info)} <span class="hint">(${it.t0.toFixed(1)} – ${it.t1.toFixed(1)} s)</span>`;
  seek(it.ev ? it.t0 : t); return true; });
