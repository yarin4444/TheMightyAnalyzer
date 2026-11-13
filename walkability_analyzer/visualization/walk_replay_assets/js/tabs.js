// ---------------------------------------------------------------- score / physiology / config / summary tabs
function card(title, body) { return `<div class="card"><h4>${title}</h4>${body}</div>`; }
function tbl(rows, cls = '') { return `<table class="${cls}">` + rows.map(r => `<tr><td>${r[0]}</td><td>${r[1] ?? '—'}</td></tr>`).join('') + '</table>'; }
const seekBtn = t => `<button data-seek="${t}" style="font-size:10px;padding:0 4px">▶ go</button>`;
function onSeekButtons(el) { el.addEventListener('click', e => { const b = e.target.closest('[data-seek]'); if (b) seek(+b.dataset.seek); }); }
const SCORE_NOTE = 'Exploratory weighted composite (thesis Chapter 7: domain sub-indices I = Σβⱼxⱼ, window score W = ΣαₖTₖIₖ / ΣαₖTₖ). The weights are not empirically validated.';

function buildScore() { const s = SUM, ow = WINS.map(w => w.owi).filter(ok), thr = CFG.poor_threshold, poor = ow.filter(v => v < thr).length;
  const worst = WINS.filter(w => ok(w.owi)).sort((a, b) => a.owi - b.owi).slice(0, 5);
  $('#scoreCards').innerHTML =
    card('Route walkability score', `<div class="bigscore" style="color:${scoreColor(s.owi)}">${f1(s.owi)}</div><div style="text-align:center" class="hint">out of 100 · route = ${esc(CFG.final)}</div>` +
      tbl([['mean window score', f1(s.owi_mean)], ['P10 window score', f1(s.owi_p10)], ['windows scored', `${s.windows_scored ?? ow.length}/${s.windows_total ?? WINS.length}`],
        ['min | median | max', `${f1(s.owi_min)} | ${f1(s.owi_median)} | ${f1(s.owi_max)}`],
        [`windows below ${thr}`, `<span style="color:var(--bad)">${poor} (${f0(s.hotspot_duration_s ?? poor * WSTEP)} s)</span>`]]) +
      `<div class="note">${SCORE_NOTE} The route-level aggregation (mean and P10) is an implementation choice of the software.</div>`) +
    card('Window score distribution', '<canvas id="hist"></canvas>') +
    card('Module breakdown (route mean, 0–100)', tbl(Object.keys(CFG.modules).map(k => { const m = CFG.modules[k], v = MOD_MEAN[k.toLowerCase()];
      return [`${m.name} (${k})<br><span class="hint">${esc(m.domain)} · weight ${Math.round(m.weight * 100)} %</span>`, m.available ? `<span style="color:${scoreColor(v)}">${f1(v)}</span>` : '<span class="hint">not used</span>']; }))) +
    card('Worst 5 moments', worst.length ? worst.map(w => `<div class="mb" style="grid-template-columns:70px 1fr 40px 54px"><span class="k">${w.t0.toFixed(1)} s</span><div class="track"><div class="fill" style="width:${w.owi}%;background:${scoreColor(w.owi)}"></div></div><span class="v">${w.owi.toFixed(1)}</span>${seekBtn(w.t0)}</div>`).join('') : '<span class="hint">no scored windows</span>') +
    card('Personal baseline', tbl([['baseline speed', `${f2(s.baseline_speed)} m/s`], ['baseline cadence', `${f1(s.baseline_cadence)} spm`],
      ['baseline HR', ok(s.hr_baseline) ? `${f1(s.hr_baseline)} ± ${f1(s.hr_sd)} bpm` : '—']])) +
    card('Gait summary', tbl([['walking time', `${f2(s.walking_time_s)} s`], [`distance (${esc(s.distance_method || 'speed')})`, `${f1(s.distance_m)} m`], ['distance (haversine sum, reference)', `${f1(s.distance_haversine_m)} m`],
      ['mean speed', `${f2(s.mean_speed)} m/s`], ['median step length', `${f2(s.median_step_length)} m`], ['mean / spectral cadence', `${f1(s.mean_cadence)} / ${f1(s.spectral_cadence)} spm`],
      ['candidate step events', s.steps], ['stops · stop time', `${s.stops ?? '—'} · ${f1(s.stop_fraction)} %`], ['slowdowns (IMU-confirmed)', s.slowdowns], ['GPS-speed artefacts', s.gps_artefacts]]));
  onSeekButtons($('#scoreCards')); }
function drawHist() { const cv = $('#hist'); if (!cv) return; const { c, w, h } = fit(cv), bins = new Array(20).fill(0); WINS.forEach(x => { if (ok(x.owi)) bins[Math.min(19, Math.floor(x.owi / 5))]++; });
  const mx = Math.max(1, ...bins), bw = (w - 20) / 20; c.fillStyle = TH.panel; c.fillRect(0, 0, w, h);
  bins.forEach((n, k) => { const bh = n / mx * (h - 28); c.fillStyle = scoreColor(k * 5 + 2.5); c.fillRect(10 + k * bw + 1, h - 16 - bh, bw - 2, bh); });
  c.fillStyle = TH.dim; c.font = '10px Consolas'; [0, 25, 50, 75, 100].forEach(v => c.fillText(v, 10 + v / 5 * bw - 6, h - 3));
  const W = winAt(S.t); if (!W || !ok(W.owi)) return; const cw = W.owi; c.strokeStyle = TH.acc; c.lineWidth = 2; c.beginPath(); c.moveTo(10 + cw / 5 * bw, 4); c.lineTo(10 + cw / 5 * bw, h - 16); c.stroke(); c.lineWidth = 1;
  c.fillStyle = TH.acc; c.fillText('now', 10 + cw / 5 * bw + 3, 12); }

function physMode() { const p = SRC.polar;
  if (!p.available) return ['Physiology unavailable', 'var(--dim)', 'No Polar file was found or aligned for this recording — PCI is not used.'];
  if (p.mode === 'full_pci') return ['Full PCI (HR + HRV)', 'var(--ok)', 'RR/RMSSD available.'];
  return ['Reduced PCI (HR only)', 'var(--ok)', 'RR intervals not present → rmssd weight redistributed to heart_rate / heart_rate_slope.']; }
function buildPhys() { const s = SUM, p = SRC.polar, [mode, col, note] = physMode(), spikes = DATA.events.filter(e => e.type === 'hr_spike');
  $('#physCards').innerHTML =
    card('Mode', `<div class="bigscore" style="font-size:22px;color:${col}">${mode}</div><div class="hint" style="text-align:center">${note}</div>` +
      (p.simulated ? '<div class="warnitem">⚠ The Polar file is SIMULATED — not a real measurement.</div>' : '')) +
    card('Heart rate', tbl([['baseline HR', ok(s.hr_baseline) ? `${f1(s.hr_baseline)} ± ${f1(s.hr_sd)} bpm` : '—'], ['mean HR', `${f1(s.hr_mean)} bpm`], ['peak HR', `${f1(s.hr_peak)} bpm`],
      ['spike threshold', ok(s.hr_threshold) ? `${f1(s.hr_threshold)} bpm` : '—'], ['HR spikes', spikes.length],
      ['window coverage', ok(s.hr_coverage) ? `${f1(s.hr_coverage)} % (${s.hr_windows?.[0] ?? '—'}/${s.hr_windows?.[1] ?? '—'} windows)` : '—']])) +
    card('Polar integration', tbl([['source file', esc(p.file)], ['synchronization', `${esc(p.sync.method)} (offset ${f2(p.sync.offset_s)} s)`], ['available columns', esc((p.columns || []).join(', ')) || '—'],
      ['HRV available', p.hrv ? 'yes' : '<span style="color:var(--bad)">no</span>'], ['included in OWI', p.scored ? '<span style="color:var(--ok)">✔ yes</span>' : '<span class="hint">no</span>'],
      ['speed cross-check', p.speed_check ? `best extra shift ${f2(p.speed_check.best_lag_s)} s (r ${p.speed_check.r_at_zero} → ${p.speed_check.r_best})` : '—']]) +
      '<div class="note">Aligned through the watch\'s recorded absolute start time (thesis Section 4.2, Stage 2). The watch does not capture the stomp-clap event, so heart rate is interpreted over event-centred windows of several seconds rather than individual seconds. The speed cross-check compares the watch\'s connected-GPS speed with the iPhone GPS speed; it bounds the alignment error and is not applied.</div>') +
    card('HR spikes', spikes.length ? spikes.map(e => `<div class="mb" style="grid-template-columns:110px 1fr 54px"><span class="k">${e.t0.toFixed(1)}–${e.t1.toFixed(1)} s</span><span>peak <b style="color:${EV.hr_spike.c}">${f0(e.details.peak_hr)}</b> bpm (${sgn(e.details.peak_hr - e.details.baseline_hr)})</span>${seekBtn(e.t0)}</div>`).join('') : '<span class="hint">none</span>') +
    (s.physio_notes?.length ? card('Notes', s.physio_notes.map(n => `<div class="warnitem">${esc(n)}</div>`).join('')) : '');
  onSeekButtons($('#physCards')); }

function buildConfig() { const m = CFG.modules, src = SRC, g = src.gopro;
  $('#configCards').innerHTML =
    card('Scoring configuration · ' + esc(META.score_version), Object.keys(m).map(k => `<div style="margin:6px 0"><b>${m[k].name} (${k})</b> <span class="hint">${esc(m[k].domain)} · weight ${Math.round(m[k].weight * 100)} %${m[k].available ? '' : ' · not used'}</span><br>` +
      Object.keys(m[k].metrics).map(x => `<span class="chip ${!m[k].available || (k === 'PCI' && x === 'rmssd' && !src.polar.hrv) ? 'na' : ''}">${x}: ${Math.round(m[k].metrics[x] * 100)}%</span>`).join('') + '</div>').join('') +
      `<div class="hint">${CFG.window_s} s windows, ${Math.round(CFG.overlap * 100)} % overlap · route = ${esc(CFG.final)}</div><div class="note">${SCORE_NOTE}</div>`) +
    card('Recording', tbl([['location', esc(META.location)], ['route ID', esc(META.route_id)], ['recording ID', esc(META.recording_id)], ['first sample (wall clock)', esc(META.wallclock0 || '—')],
      ['sampling rate', `${META.fs_hz} Hz`], ['walking segment', `${T0.toFixed(2)} – ${T1.toFixed(2)} s (${D.toFixed(2)} s)`], ['time base', esc(META.time_base)],
      ['analysis date', esc(META.analysis_date)], ['pipeline', esc(META.pipeline_version)]])) +
    card('Sources & synchronization', tbl([['iPhone IMU + GPS', 'reference timeline (shared phone clock)'],
      ['Polar', src.polar.available ? `${esc(src.polar.file)} · ${esc(src.polar.sync.method)} · offset ${f2(src.polar.sync.offset_s)} s` : 'not available'],
      ['GoPro', g.available ? `${esc(g.file)}${g.proxy ? ' → H.264 proxy' : ''} · ${esc(g.codec)} ${g.width}×${g.height} · ${f2(g.fps)} fps` : 'not available'],
      ['GoPro sync', g.available && VID.synced ? `stomp-clap start anchor: t<sub>v</sub> = t + Δ, Δ = ${VID.delta.toFixed(3)} s (α = 1)` : g.available ? 'not synchronized' : '—'],
      ['clap anchors (video)', g.available && ok(g.sync?.clap_start_s) ? `start ${f2(g.sync.clap_start_s)} s (${f1(g.sync.clap_start_ratio)}× thr) · end ${f2(g.sync.clap_end_s)} s (${f1(g.sync.clap_end_ratio)}× thr) · ${esc(g.sync.clap_method)}, high-pass ${g.sync.clap_highpass_hz} Hz` : '—'],
      ['pipeline video mapping', g.available && ok(g.sync?.pipeline_a) ? `t = ${g.sync.pipeline_a} · t<sub>v</sub> + ${g.sync.pipeline_b}` : '—']])) +
    card('Processing parameters (thesis Table 5)', tbl(CFG.parameters.map(([n, v, impl]) => [`${esc(n)}<br><span class="hint">${esc(impl)}</span>`, esc(v)]), 'wide')) +
    card(`Data-quality warnings (${DATA.warnings.length})`, DATA.warnings.map(w => `<div class="warnitem">⚠ ${esc(w)}</div>`).join('') || '<span class="hint">none</span>'); }

function buildSummary() { const s = SUM, m = META, p = SRC.polar, [mode] = physMode();
  const evRows = DATA.events.map(e => `<tr><td><span class="dot" style="background:${EV[e.type].c}"></span>${EV[e.type].n}</td><td>${e.t0.toFixed(1)} – ${e.t1.toFixed(1)} s</td><td>${esc(e.label)}${e.type === 'hr_spike' ? ` — peak ${f0(e.details.peak_hr)} bpm, baseline ${f0(e.details.baseline_hr)} bpm, threshold ${f0(e.details.threshold_bpm)} bpm` : ''}</td></tr>`).join('');
  $('#summary').innerHTML = `
    <h1>🚶 Walkability Analysis Report</h1>
    <table><tr><td>Location</td><td>${esc(m.location)}</td></tr><tr><td>Route ID</td><td>${esc(m.route_id)}</td></tr><tr><td>Recording ID</td><td>${esc(m.recording_id)}</td></tr>
      <tr><td>Sampling rate</td><td>${m.fs_hz} Hz</td></tr><tr><td>Walking segment</td><td>${T0.toFixed(1)} – ${T1.toFixed(1)} s (sensor time)</td></tr><tr><td>Analysis date</td><td>${esc(m.analysis_date)}</td></tr>
      <tr><td>Pipeline</td><td>${esc(m.pipeline_version)}</td></tr></table>
    ${m.description ? `<h2>Route description</h2><p>${esc(m.description)}</p>` : ''}
    <h2>📊 Key metrics</h2><div class="metrics">${s.cards.map(([l, v, u]) => `<div class="metric"><div class="l">${esc(l)}</div><div class="v">${esc(v)} <span class="u">${esc(u)}</span></div></div>`).join('')}</div>
    <h2>📈 Walking profile</h2>${EXTRAS.plot_png ? `<img src="${EXTRAS.plot_png}" alt="Walking profile">` : '<p class="hint">plot image not available</p>'}
    <div class="snap" id="snaps"></div>
    <h2>❤️ Physiology</h2><table><tr><td>Mode</td><td>${mode}${p.simulated ? ' — <b>SIMULATED data</b>' : ''}</td></tr>
      ${p.available ? `<tr><td>Polar file</td><td>${esc(p.file)} (${esc(p.sync.method)}, offset ${f2(p.sync.offset_s)} s)</td></tr><tr><td>Baseline / mean / peak HR</td><td>${f1(s.hr_baseline)} ± ${f1(s.hr_sd)} / ${f1(s.hr_mean)} / ${f1(s.hr_peak)} bpm</td></tr><tr><td>Window coverage</td><td>${f1(s.hr_coverage)} %</td></tr>` : ''}</table>
    <h2>🔍 Detected events (${DATA.events.length})</h2>${evRows ? `<table>${evRows}</table>` : '<p class="hint">none</p>'}
    <h2>🗺️ Route map</h2><p>${EXTRAS.map ? `Interactive map: <a href="${EXTRAS.map}" target="_blank">${esc(decodeURIComponent(EXTRAS.map))}</a>. ` : ''}The Route map panel of this report shows the track coloured by window score.</p>
    <h2>🎯 Walkability score</h2>
    <table><tr><td>Route score</td><td><b style="color:${scoreColor(s.owi)}">${f1(s.owi)}</b> / 100 (${esc(m.score_version)})</td></tr><tr><td>Mean · P10 window score</td><td>${f1(s.owi_mean)} · ${f1(s.owi_p10)}</td></tr>
      <tr><td>Windows scored</td><td>${s.windows_scored ?? '—'}/${s.windows_total ?? '—'}</td></tr><tr><td>Min | median | max</td><td>${f1(s.owi_min)} | ${f1(s.owi_median)} | ${f1(s.owi_max)}</td></tr>
      <tr><td>Windows below ${CFG.poor_threshold}</td><td>${s.hotspot_count ?? '—'} (${f0(s.hotspot_duration_s)} s)</td></tr>
      <tr><td>Personal baseline</td><td>speed ${f2(s.baseline_speed)} m/s · cadence ${f1(s.baseline_cadence)} spm</td></tr></table>
    <h2>📐 Score breakdown</h2><table><tr><th>Module</th><th>Mean (0–100)</th><th>Weight</th><th>Metrics</th></tr>${Object.keys(CFG.modules).map(k => { const md = CFG.modules[k];
      return `<tr><td>${md.name} (${k})</td><td>${md.available ? f1(MOD_MEAN[k.toLowerCase()]) : 'not used'}</td><td>${Math.round(md.weight * 100)} %</td><td>${Object.entries(md.metrics).map(([x, w]) => `${x} ${Math.round(w * 100)}%`).join(', ')}</td></tr>`; }).join('')}</table>
    <p class="note">${CFG.window_s} s windows, ${Math.round(CFG.overlap * 100)} % overlap. Route score = ${esc(CFG.final)}. ${SCORE_NOTE}</p>
    ${DATA.warnings.length ? `<h2>⚠ Data-quality warnings</h2>${DATA.warnings.map(w => `<div class="warnitem">${esc(w)}</div>`).join('')}` : ''}
    ${EXTRAS.classic ? `<p class="note">Classic static report: <a href="${EXTRAS.classic}" target="_blank">${esc(decodeURIComponent(EXTRAS.classic))}</a></p>` : ''}`; }
// static plot snapshots for the printed summary
function snapPlots() { const box = $('#snaps'); if (!box) return; const imgs = plotCanvases.filter(cv => cv.width > 0).map(cv => `<img src="${cv.toDataURL('image/png')}" alt="${cv.dataset.plot}">`);
  box.innerHTML = imgs.join(''); }
