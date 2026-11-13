// ---------------------------------------------------------------- GoPro panel: <video> synced to the master clock, HUD, thumbnails
const GP = SRC.gopro || { available: false }, video = $('#video'), cvThumb = $('#cvThumb'), noVideo = $('#noVideo');
const VID = { synced: !!(GP.available && GP.sync && ok(GP.sync.delta_s)), delta: GP.sync?.delta_s ?? 0, ready: false, master: false, failed: false };
// thesis Section 4.2: video time t_v = t + Δ (start stomp-clap anchor, α = 1)
const tv = t => t + VID.delta;
const vidDur = () => (ok(video.duration) && video.duration > 0) ? video.duration : (GP.duration_s || 0);
const inVideo = t => VID.ready && tv(t) >= 0 && tv(t) <= vidDur() - 0.05;
const THUMBS = GP.thumbs || null, THUMB_IMG = THUMBS ? Object.assign(new Image(), { src: THUMBS.sprite }) : null;
if (THUMB_IMG) THUMB_IMG.onload = () => { S.dirty = true; };

function showNoVideo(html) { noVideo.innerHTML = html; noVideo.style.display = 'flex'; }
function initVideo() {
  if (!GP.available) { showNoVideo('<b>No GoPro video for this recording</b><span>The report works without video; all other panels are synced to the IMU/GPS clock.</span>'); return; }
  video.src = GP.src;
  if (!VID.synced) video.controls = true;
  video.addEventListener('loadedmetadata', () => { VID.ready = true; VID.failed = false; noVideo.style.display = 'none'; cvThumb.style.display = 'none'; video.style.display = 'block'; VID.syncTo(S.t); S.dirty = true; });
  video.addEventListener('error', () => { VID.ready = false; VID.failed = true; video.style.display = 'none';
    if (THUMBS && VID.synced) cvThumb.style.display = 'block';
    showNoVideo(`<b>Video not found or not playable</b><span>${esc(decodeURIComponent(GP.src))}</span><span>Use “Load video…” to pick ${esc(GP.file)}${GP.proxy ? ' (or its _proxy.mp4)' : ''}.${THUMBS && VID.synced ? ' Thumbnails are shown meanwhile.' : ''}</span>`);
    if (THUMBS && VID.synced) noVideo.style.background = 'transparent', noVideo.style.justifyContent = 'flex-end';
    S.dirty = true; });
  video.addEventListener('ended', () => { VID.master = false; });
  $('#fileVideo').addEventListener('change', e => { const f = e.target.files[0]; if (!f) return; noVideo.style.display = 'none'; video.style.display = 'block'; video.src = URL.createObjectURL(f); });
}
VID.syncTo = t => { if (!VID.ready || !VID.synced) return; if (inVideo(t)) { if (Math.abs(video.currentTime - tv(t)) > 0.12) video.currentTime = tv(t); } else if (!video.paused) video.pause(); };
VID.play = () => { if (!VID.ready || !VID.synced || !inVideo(S.t)) { VID.master = false; return; }
  video.playbackRate = Math.min(16, S.rate); VID.syncTo(S.t); VID.master = true; video.play().catch(() => { VID.master = false; }); };
VID.pause = () => { VID.master = false; if (VID.ready && VID.synced && !video.paused) video.pause(); };
// while playing, the video is the clock master: t = t_v − Δ
VID.clock = () => (VID.master && !video.paused && !video.seeking) ? video.currentTime - VID.delta : null;
SEEK_HOOKS.push(t => VID.syncTo(t));

function drawThumb() { if (cvThumb.style.display !== 'block' || !THUMB_IMG || !THUMB_IMG.complete) return;
  const { c, w, h } = fit(cvThumb), k = nearestIdx(THUMBS.t, tv(S.t)), sx = (k % THUMBS.cols) * THUMBS.w, sy = Math.floor(k / THUMBS.cols) * THUMBS.h;
  const sc = Math.min(w / THUMBS.w, h / THUMBS.h); c.fillStyle = '#000'; c.fillRect(0, 0, w, h);
  c.drawImage(THUMB_IMG, sx, sy, THUMBS.w, THUMBS.h, (w - THUMBS.w * sc) / 2, (h - THUMBS.h * sc) / 2, THUMBS.w * sc, THUMBS.h * sc); }

function drawHud() {
  const t = S.t, W = winAt(t), act = activeEvents(t).filter(e => e.type !== 'video');
  let tl;
  if (!GP.available) tl = `walk t = <b>${t.toFixed(1)} s</b>`;
  else if (!VID.synced) tl = `<span class="bad">GoPro NOT SYNCHRONIZED</span><br>walk t = <b>${t.toFixed(1)} s</b>`;
  else tl = `<span class="rec">●</span> GoPro video t<sub>v</sub> = <b>${fmtT(tv(t))}</b>${inVideo(t) || !VID.ready ? '' : ' <span class="bad">(outside video)</span>'}${GP.sync.suspect ? ' <span class="bad">SYNC SUSPECT</span>' : ''}<br>walk t = <b>${t.toFixed(1)} s</b> · Δ = ${VID.delta.toFixed(2)} s`;
  $('#hudTL').innerHTML = tl;
  $('#hudTR').innerHTML = (W && ok(W.owi) ? `OWI <b style="color:${scoreColor(W.owi)}">${W.owi.toFixed(1)}</b><br>` : '') +
    act.map(e => `<span class="evt" style="background:${EV[e.type].c}">${EV[e.type].n.toUpperCase()}</span>`).join('<br>');
  const d = sigAt('dist', t);
  $('#hudBL').innerHTML = `GPS speed <b>${f2(sigAt('speed_gps', t))}</b> m/s · step rate <b>${f0(sigAt('cadence', t))}</b> spm` +
    (HAS_HR ? ` · HR <b>${f0(sigAt('hr', t))}</b> bpm` : '') + (ok(d) ? ` · dist <b>${d.toFixed(0)}</b> m` : '');
}
