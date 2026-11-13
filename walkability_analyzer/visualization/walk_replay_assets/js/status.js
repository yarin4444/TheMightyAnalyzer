// ---------------------------------------------------------------- live status panel
const cvGauge = $('#cvGauge');
function drawGauge(v) { const { c, w, h } = fit(cvGauge), cx = w / 2, cy = h - 18, r = Math.min(w / 2 - 10, h - 26), a0 = Math.PI * .85, a1 = Math.PI * 2.15;
  c.clearRect(0, 0, w, h); c.lineCap = 'round'; c.lineWidth = 10; c.strokeStyle = TH.panel2; c.beginPath(); c.arc(cx, cy, r, a0, a1); c.stroke();
  for (let k = 0; k < 40; k++) { const s = k / 40 * 100; c.strokeStyle = scoreColor(s); c.globalAlpha = ok(v) && s <= v ? 1 : .15;
    c.beginPath(); c.arc(cx, cy, r, a0 + (a1 - a0) * k / 40, a0 + (a1 - a0) * (k + .7) / 40); c.stroke(); }
  c.globalAlpha = 1; const ap = a0 + (a1 - a0) * (CFG.poor_threshold || 35) / 100; c.strokeStyle = TH.fg; c.lineWidth = 2; c.lineCap = 'butt';
  c.beginPath(); c.moveTo(cx + Math.cos(ap) * (r - 9), cy + Math.sin(ap) * (r - 9)); c.lineTo(cx + Math.cos(ap) * (r + 9), cy + Math.sin(ap) * (r + 9)); c.stroke();
  c.fillStyle = scoreColor(v); c.font = 'bold 26px Consolas'; c.textAlign = 'center'; c.fillText(ok(v) ? v.toFixed(1) : '—', cx, cy - 6);
  c.fillStyle = TH.dim; c.font = '10px Segoe UI'; c.fillText('window OWI', cx, cy + 9); c.textAlign = 'left'; }

function lampsSpec() { const p = SRC.polar, g = SRC.gopro, fs = SRC.imu.fs_hz;
  return [
    [`IMU ${f0(fs)} Hz`, !SRC.imu.available ? 'bad' : fs < 50 ? 'warn' : 'ok', 'lp-imu', SRC.imu.available ? `coverage ${f0(100 * (SRC.imu.coverage ?? 1))} %` : 'missing'],
    ['GPS', SRC.gps.available ? 'ok' : 'bad', 'lp-gps', SRC.gps.available ? `median hacc ${f1(SRC.gps.hacc_median)} m` : 'missing'],
    [p.simulated ? 'Polar HR (SIMULATED)' : 'Polar HR', !p.available ? 'bad' : p.simulated ? 'warn' : 'ok', 'lp-hr', p.available ? p.file : 'no Polar file'],
    ['Polar HRV', p.available && p.hrv ? 'ok' : 'bad', 'lp-hrv', p.hrv ? 'RR / RMSSD available' : 'no RR intervals in export'],
    ['GoPro', !g.available ? 'bad' : 'ok', 'lp-gopro', g.available ? g.file : 'no video'],
    ['Sync', !g.available ? '' : VID.synced ? (g.sync.suspect ? 'warn' : 'ok') : 'warn', 'lp-sync', VID.synced ? `stomp-clap Δ = ${VID.delta.toFixed(2)} s${g.sync.suspect ? ' — SUSPECT, verify visually' : ''}` : g.available ? 'video not synchronized' : 'IMU/GPS share the phone clock']]; }

function buildStatus() { const s = SUM;
  $('#routeBox').innerHTML = HAS_OWI ? `Route score<br><span class="big" style="color:${scoreColor(s.owi)}">${f1(s.owi)}</span> <span>/ 100</span><br>
    mean <b>${f1(s.owi_mean)}</b> · P10 <b>${f1(s.owi_p10)}</b><br>windows <b>${s.windows_scored ?? WINS.length}/${s.windows_total ?? WINS.length}</b> · ${esc(META.score_version)}<br><span class="hint">exploratory composite, not validated</span>`
    : `Route score<br><span class="big">${f1(s.owi)}</span><br><span class="hint">${esc(META.score_version)} (no per-window scores)</span>`;
  $('#mods').innerHTML = MOD_KEYS.map(k => `<div class="mod ${MOD_AVAIL[k] ? '' : 'na'}" title="${MOD_AVAIL[k] ? '' : 'module not used in this recording'}"><span class="k">${k.toUpperCase()}</span><div class="track"><div class="fill" id="mf-${k}"></div>
    ${ok(MOD_MEAN[k]) ? `<div class="tick" style="left:${MOD_MEAN[k]}%"></div>` : ''}</div><span class="v" id="mv-${k}"></span></div>`).join('');
  $('#lamps').innerHTML = lampsSpec().map(([n, c, id, tip]) => `<span class="lamp ${c}" id="${id}" title="${esc(tip)}">${esc(n)}</span>`).join('') +
    (SRC.polar.available && !SRC.polar.hrv ? '<div class="hint" style="width:100%;margin-top:3px">Reduced PCI (HR only)</div>' : '');
  let html = '';
  for (const M in CFG.modules) { const mod = CFG.modules[M]; html += `<div class="mgroup">${M} · ${esc(mod.domain)} · ${Math.round(mod.weight * 100)} %${mod.available ? '' : ' · not used'}</div>`;
    for (const k in mod.metrics) html += `<div class="mb" id="mb-${k}"><span class="k" title="${M}">${k}</span><div class="track"><div class="fill"></div></div><span class="v"></span><span class="w">${Math.round(mod.metrics[k] * 100)}%</span></div>`; }
  $('#mbars').innerHTML = html; }

function gaitState(t) { const act = activeEvents(t), has = ty => act.find(e => e.type === ty);
  const ev = has('stop') || has('slowdown') || has('change') || has('gps_artifact');
  const state = has('stop') ? 'stop' : has('slowdown') ? 'slowdown' : has('change') ? 'change' : has('gps_artifact') ? 'gps' : 'walk';
  return { state, reason: ev ? ev.label : 'no event — IMU step rate and GPS speed consistent', act }; }

function updateStatus() { const t = S.t, W = winAt(t), g = gaitState(t);
  drawGauge(W ? W.owi : null);
  $('#winLabel').textContent = W ? `window #${W.i} · ${W.t0.toFixed(1)}–${W.t1.toFixed(1)} s` : 'no scoring windows';
  for (const k of MOD_KEYS) { const el = $('#mf-' + k), v = W ? W[k] : null; el.style.width = (ok(v) ? v : 0) + '%'; el.style.background = scoreColor(v); $('#mv-' + k).textContent = ok(v) ? v.toFixed(1) : 'n/a'; }
  document.querySelectorAll('#gaitChips span').forEach(s => { s.className = s.dataset.s === g.state ? 'on' + (g.state === 'stop' ? ' bad' : g.state === 'walk' ? '' : ' warn') : ''; });
  $('#gaitReason').textContent = g.reason;
  if (SRC.gps.available) $('#lp-gps').className = 'lamp ' + (g.act.some(e => e.type === 'gps_artifact') ? 'warn' : 'ok');
  const v = sigAt('speed_gps', t), vm = sigAt('speed_med', t), cad = sigAt('cadence', t), hr = sigAt('hr', t), d = sigAt('dist', t);
  const nSteps = DATA.steps_t.length ? bsearch(DATA.steps_t, t) + (t >= DATA.steps_t[0] ? 1 : 0) : 0;
  const stepLen = ok(vm) && ok(cad) && cad > 10 ? vm / (cad / 60) : null;
  const kv = [['GPS speed · 2 s median', `${f2(v)} · ${f2(vm)} m/s`], [`step rate (${CFG.thresholds?.cadence_window_s ?? 5} s)`, `${f0(cad)} spm`],
    ['spectral cadence (route)', `${f1(SUM.spectral_cadence)} spm`], ['implied step length v / rate', `${f2(stepLen)} m`],
    ['RMS aᵥ (1 s)', `${f2(sigAt('acc_rms', t))} m/s²`], ['steps so far', `${nSteps} / ${DATA.steps_t.length}`],
    ['distance so far', `${f0(d)} / ${f0(SUM.distance_m)} m`], ['elapsed', `${fmtT(t - T0)} / ${fmtT(D)}`]];
  if (HAS_HR) kv.push(['heart rate', `${f0(hr)} bpm`], ['HR − baseline', `${sgn(ok(hr) && ok(SUM.hr_baseline) ? hr - SUM.hr_baseline : null)} bpm`]);
  kv.push(['baseline speed · cadence', `${f2(SUM.baseline_speed)} m/s · ${f1(SUM.baseline_cadence)} spm`]);
  $('#kv').innerHTML = kv.map(([k, x]) => `<span class="k">${k}</span><span class="v">${x}</span>`).join('');
  document.querySelectorAll('#mbars .mb').forEach(row => { const k = row.id.slice(3), val = W && W.metrics ? W.metrics[k] : null;
    row.classList.toggle('na', !ok(val)); const fl = row.querySelector('.fill'); fl.style.width = (ok(val) ? val : 0) + '%'; fl.style.background = scoreColor(val);
    row.querySelector('.v').textContent = ok(val) ? val.toFixed(0) : 'n/a'; });
  $('#activeEv').innerHTML = g.act.length ? g.act.map(e => `<div style="border-color:${EV[e.type].c}">${EV[e.type].n}: ${esc(e.label)}</div>`).join('') : '<span class="hint">none</span>'; }
