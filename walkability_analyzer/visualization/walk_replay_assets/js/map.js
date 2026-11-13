// ---------------------------------------------------------------- route map: Leaflet + OSM tiles when online, canvas projection offline
const cvMap = $('#cvMap'), leafBox = $('#leaflet');
const MAPS = { mode: 'none', leaflet: null, k: null, ox: 0, oy: 0 };
const R_EARTH = 6371000;
// local tangent plane at the route centroid (thesis Section 4.5): x = R(λ−λ0)cosφ0, y = R(φ−φ0)
const TRP = TRACK ? (() => { const la0 = mean(TRACK.lat) * Math.PI / 180, lo0 = mean(TRACK.lon) * Math.PI / 180;
  return { x: TRACK.lon.map(l => R_EARTH * (l * Math.PI / 180 - lo0) * Math.cos(la0)), y: TRACK.lat.map(l => R_EARTH * (l * Math.PI / 180 - la0)) }; })() : null;
const HR_RANGE = HAS_HR ? [pct(SIG.hr, 2), pct(SIG.hr, 98)] : [0, 1];
function mapValue(mode, t) {
  if (mode === 'owi') { const w = winAt(t); return w ? w.owi : null; }
  if (mode === 'speed') { const v = sigAt('speed_med', t) ?? sigAt('speed_gps', t); return ok(v) ? clamp((v - .4) / 1.2 * 100, 0, 100) : null; }
  const hr = sigAt('hr', t); return ok(hr) ? clamp(100 - (hr - HR_RANGE[0]) / Math.max(1, HR_RANGE[1] - HR_RANGE[0]) * 100, 0, 100) : null; }
function legend() { const mode = $('#selMapMode').value;
  $('#legTitle').textContent = { owi: 'OWI score (window)', speed: 'GPS speed (2 s median)', hr: 'heart rate (high = red)' }[mode];
  $('#legRange').textContent = mode === 'owi' ? '0 · 50 · 100' : mode === 'speed' ? '0.4 → 1.6 m/s' : `${f0(HR_RANGE[1])} ← ${f0(HR_RANGE[0])} bpm`; }
function nearestTrackT(px, py, toXY) { let best = -1, bd = 1e9;
  for (let i = 0; i < TRACK.t.length; i++) { const p = toXY(i), d = Math.hypot(p[0] - px, p[1] - py); if (d < bd) { bd = d; best = i; } }
  return bd < 25 ? TRACK.t[best] : null; }
const evOnMap = () => DATA.events.filter(e => e.type !== 'video' && e.type !== 'gps_artifact' && ok(e.t0));
const trackPos = t => [interp(TRACK.t, TRACK.lat, clamp(t, TRACK.t[0], TRACK.t[TRACK.t.length - 1])), interp(TRACK.t, TRACK.lon, clamp(t, TRACK.t[0], TRACK.t[TRACK.t.length - 1]))];

// ---- Leaflet
function initLeaflet() {
  const map = L.map(leafBox, { preferCanvas: true, zoomControl: true, attributionControl: true });
  let loaded = 0, errors = 0;
  // OSM and CARTO tile servers reject pages opened from file:// (no Referer); Esri tiles do not
  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
  const bases = {
    'Streets (Esri)': L.tileLayer(ESRI + 'World_Street_Map/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Tiles © Esri' }),
    'Satellite (Esri)': L.tileLayer(ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 19, attribution: 'Tiles © Esri' }),
  };
  Object.values(bases).forEach(b => b.on('tileload', () => loaded++).on('tileerror', () => { if (++errors >= 6 && loaded === 0) useCanvasMap('map tiles unavailable — offline map'); }));
  bases['Streets (Esri)'].addTo(map);
  L.control.layers(bases, null, { position: 'topright', collapsed: true }).addTo(map);
  const ll = TRACK.t.map((_, i) => [TRACK.lat[i], TRACK.lon[i]]);
  const segs = [];
  for (let i = 1; i < ll.length; i++) {
    const art = TRACK.gps_quality[i] < 1;
    const seg = L.polyline([ll[i - 1], ll[i]], { weight: 5, opacity: .95, dashArray: art ? '5 5' : null, color: art ? '#8a8f99' : '#888' }).addTo(map);
    seg.on('click', () => seek(TRACK.t[i])); seg._art = art; seg._t = TRACK.t[i]; segs.push(seg); }
  const fixes = L.layerGroup(ll.map((p, i) => L.circleMarker(p, { radius: 1.6, weight: 0, fillColor: '#c9d1dc', fillOpacity: .6, interactive: false }))).addTo(map);
  const evLayer = L.layerGroup(evOnMap().map(e => { const p = trackPos(e.t0);
    return L.circleMarker(p, { radius: 7, color: '#0d1117', weight: 2, fillColor: EV[e.type].c, fillOpacity: 1 })
      .bindTooltip(`${esc(EV[e.type].n)} · ${e.t0.toFixed(1)}–${e.t1.toFixed(1)} s<br>${esc(e.label)}`).on('click', () => seek(e.t0)); })).addTo(map);
  const tail = L.polyline([], { color: '#4cc2ff', weight: 3, opacity: .9, interactive: false }).addTo(map);
  const icon = L.divIcon({ className: 'walker', iconSize: [34, 34], iconAnchor: [17, 17],
    html: '<svg width="34" height="34" viewBox="-17 -17 34 34"><circle r="15" fill="none" stroke="#4cc2ff" stroke-opacity=".45" stroke-width="2"/><g class="arr"><path d="M0,-11 L7,7 L0,3 L-7,7 Z" fill="#4cc2ff" stroke="#001018" stroke-width="1.5"/></g></svg>' });
  const walker = L.marker(ll[0], { icon, interactive: false, keyboard: false, zIndexOffset: 1000 }).addTo(map);
  map.fitBounds(L.latLngBounds(ll), { padding: [20, 20] });
  map.on('dblclick', () => map.fitBounds(L.latLngBounds(ll), { padding: [20, 20] }));
  MAPS.leaflet = { map, segs, fixes, evLayer, tail, walker, lastMode: null, lastT: null };
  $('#mapHint').textContent = 'click track to seek · wheel zoom · drag pan · dbl-click fit';
}
function recolorLeaflet(mode) { MAPS.leaflet.segs.forEach(s => { if (!s._art) s.setStyle({ color: scoreColor(mapValue(mode, s._t)) }); }); }
function drawLeaflet() { const M = MAPS.leaflet, mode = $('#selMapMode').value;
  if (M.lastMode !== mode) { recolorLeaflet(mode); M.lastMode = mode; legend(); }
  const showRaw = $('#chkRaw').checked, showEv = $('#chkEv').checked;
  if (showRaw !== M.map.hasLayer(M.fixes)) showRaw ? M.fixes.addTo(M.map) : M.fixes.remove();
  if (showEv !== M.map.hasLayer(M.evLayer)) showEv ? M.evLayer.addTo(M.map) : M.evLayer.remove();
  if (M.lastT === S.t) return; M.lastT = S.t;
  const p = trackPos(S.t); if (!ok(p[0])) return;
  M.walker.setLatLng(p);
  const arr = M.walker.getElement()?.querySelector('.arr'); if (arr) arr.setAttribute('transform', `rotate(${interp(TRACK.t, TRACK.heading, S.t) || 0})`);
  const i0 = bsearch(TRACK.t, S.t - 30), i1 = bsearch(TRACK.t, S.t), pts = [];
  for (let i = i0; i <= i1; i++) pts.push([TRACK.lat[i], TRACK.lon[i]]); pts.push(p); M.tail.setLatLngs(pts);
  if (S.playing && !M.map.getBounds().pad(-.1).contains(p)) M.map.panTo(p, { animate: false });
}

// ---- canvas fallback (offline)
const mx = x => MAPS.ox + MAPS.k * x, my = y => MAPS.oy - MAPS.k * y;
function mapFit() { const w = cvMap.clientWidth, h = cvMap.clientHeight, x0 = Math.min(...TRP.x), x1 = Math.max(...TRP.x), y0 = Math.min(...TRP.y), y1 = Math.max(...TRP.y);
  MAPS.k = Math.min((w - 40) / (x1 - x0 || 1), (h - 40) / (y1 - y0 || 1)); MAPS.ox = w / 2 - MAPS.k * (x0 + x1) / 2; MAPS.oy = h / 2 + MAPS.k * (y0 + y1) / 2; S.dirty = true; }
function drawCanvasMap() { const { c, w, h } = fit(cvMap); if (MAPS.k == null) mapFit(); const mode = $('#selMapMode').value, tr = TRACK; legend();
  c.fillStyle = TH.panel2; c.fillRect(0, 0, w, h);
  const step = niceStep(w / MAPS.k, 8); c.strokeStyle = TH.grid; c.lineWidth = 1; c.beginPath();
  for (let gx = Math.floor(-MAPS.ox / MAPS.k / step) * step; mx(gx) < w; gx += step) { c.moveTo(mx(gx), 0); c.lineTo(mx(gx), h); }
  for (let gy = Math.floor((MAPS.oy - h) / MAPS.k / step) * step; my(gy) > 0; gy += step) { c.moveTo(0, my(gy)); c.lineTo(w, my(gy)); } c.stroke();
  c.strokeStyle = TH.line; c.lineWidth = 14 * Math.min(1.5, Math.max(.5, MAPS.k / 1.2)); c.lineCap = 'round'; c.lineJoin = 'round'; c.beginPath();
  TRP.x.forEach((x, i) => i ? c.lineTo(mx(x), my(TRP.y[i])) : c.moveTo(mx(x), my(TRP.y[i]))); c.stroke();
  if ($('#chkRaw').checked) { c.fillStyle = hexA('#c9d1dc', .6); TRP.x.forEach((x, i) => c.fillRect(mx(x) - 1.2, my(TRP.y[i]) - 1.2, 2.4, 2.4)); }
  c.lineWidth = 4;
  for (let i = 1; i < tr.t.length; i++) { const art = tr.gps_quality[i] < 1; c.strokeStyle = art ? '#8a8f99' : scoreColor(mapValue(mode, tr.t[i]));
    c.setLineDash(art ? [4, 4] : []); c.beginPath(); c.moveTo(mx(TRP.x[i - 1]), my(TRP.y[i - 1])); c.lineTo(mx(TRP.x[i]), my(TRP.y[i])); c.stroke(); }
  c.setLineDash([]);
  if ($('#chkEv').checked) evOnMap().forEach(e => { const tt = clamp(e.t0, tr.t[0], tr.t[tr.t.length - 1]);
    const x = mx(interp(tr.t, TRP.x, tt)), y = my(interp(tr.t, TRP.y, tt)); c.fillStyle = EV[e.type].c; c.strokeStyle = TH.panel; c.lineWidth = 2;
    c.beginPath(); c.arc(x, y, 6, 0, 7); c.fill(); c.stroke(); c.fillStyle = '#fff'; c.font = 'bold 8px Segoe UI'; c.textAlign = 'center'; c.fillText(e.type[0].toUpperCase(), x, y + 3); c.textAlign = 'left'; });
  const i0 = bsearch(tr.t, S.t - 30); c.strokeStyle = TH.acc; c.lineWidth = 3; c.globalAlpha = .9; c.beginPath();
  for (let i = i0; i <= bsearch(tr.t, S.t); i++) i === i0 ? c.moveTo(mx(TRP.x[i]), my(TRP.y[i])) : c.lineTo(mx(TRP.x[i]), my(TRP.y[i]));
  c.lineTo(mx(interp(tr.t, TRP.x, S.t)), my(interp(tr.t, TRP.y, S.t))); c.stroke(); c.globalAlpha = 1;
  const px = mx(interp(tr.t, TRP.x, S.t)), py = my(interp(tr.t, TRP.y, S.t)), hd = (interp(tr.t, tr.heading, S.t) || 0) * Math.PI / 180;
  c.save(); c.translate(px, py); c.rotate(hd); c.fillStyle = TH.acc; c.strokeStyle = '#001018'; c.lineWidth = 1.5;
  c.beginPath(); c.moveTo(0, -11); c.lineTo(7, 7); c.lineTo(0, 3); c.lineTo(-7, 7); c.closePath(); c.fill(); c.stroke(); c.restore();
  c.beginPath(); c.arc(px, py, 16, 0, 7); c.strokeStyle = hexA('#4cc2ff', .45); c.lineWidth = 2; c.stroke();
  const sb = niceStep(w / MAPS.k, 5); c.fillStyle = TH.fg; c.fillRect(10, h - 14, sb * MAPS.k, 3); c.font = '10px Consolas'; c.fillText(sb + ' m', 10, h - 18);
  c.fillStyle = TH.dim; c.font = 'bold 12px Segoe UI'; c.fillText('N ↑', w - 30, 18); }
function initCanvasNav() { let drag = null;
  cvMap.addEventListener('mousedown', e => drag = { x: e.clientX, y: e.clientY, ox: MAPS.ox, oy: MAPS.oy, moved: false });
  window.addEventListener('mousemove', e => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    MAPS.ox = drag.ox + dx; MAPS.oy = drag.oy + dy; S.dirty = true; });
  window.addEventListener('mouseup', e => { if (drag && !drag.moved && e.target === cvMap) { const t = nearestTrackT(e.offsetX, e.offsetY, i => [mx(TRP.x[i]), my(TRP.y[i])]); if (t != null) seek(t); } drag = null; });
  cvMap.addEventListener('wheel', e => { e.preventDefault(); const z = e.deltaY < 0 ? 1.2 : 1 / 1.2; MAPS.ox = e.offsetX - (e.offsetX - MAPS.ox) * z; MAPS.oy = e.offsetY - (e.offsetY - MAPS.oy) * z; MAPS.k *= z; S.dirty = true; }, { passive: false });
  cvMap.addEventListener('dblclick', mapFit); }
function useCanvasMap(reason) { if (MAPS.mode === 'canvas') return; if (MAPS.leaflet) { MAPS.leaflet.map.remove(); MAPS.leaflet = null; }
  MAPS.mode = 'canvas'; leafBox.style.display = 'none'; cvMap.style.display = 'block'; MAPS.k = null;
  $('#mapHint').textContent = (reason ? reason + ' · ' : '') + 'local tangent plane at the route centroid · click track to seek · wheel zoom · drag pan · dbl-click fit'; S.dirty = true; }

function initMap() {
  ['selMapMode', 'chkRaw', 'chkEv'].forEach(id => $('#' + id).addEventListener('change', () => S.dirty = true));
  if (!TRACK || !SRC.gps.available) { MAPS.mode = 'none'; leafBox.style.display = 'none';
    $('#mapBox').insertAdjacentHTML('beforeend', '<div class="novideo" style="display:flex"><b>No GPS track</b><span>The recording has no valid latitude/longitude samples.</span></div>');
    document.querySelector('.maplegend').style.display = 'none'; return; }
  initCanvasNav();
  if (window.L && navigator.onLine !== false) { try { initLeaflet(); MAPS.mode = 'leaflet'; return; } catch (err) { console.warn('Leaflet failed', err); } }
  useCanvasMap(window.L ? 'offline' : '');
}
function drawMap() { if (MAPS.mode === 'leaflet') drawLeaflet(); else if (MAPS.mode === 'canvas') drawCanvasMap(); }
