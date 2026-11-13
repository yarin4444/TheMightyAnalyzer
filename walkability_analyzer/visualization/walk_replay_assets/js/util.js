// ---------------------------------------------------------------- utilities
const $ = s => document.querySelector(s);
const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
const ok = v => v != null && Number.isFinite(v);
// index of the last element <= x (0 if x is before the first element)
function bsearch(a, x) { let lo = 0, hi = a.length - 1; if (!a.length || x <= a[0]) return 0; if (x >= a[hi]) return hi;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (a[m] <= x) lo = m; else hi = m; } return lo; }
function nearestIdx(a, x) { const i = bsearch(a, x); return i < a.length - 1 && Math.abs(a[i + 1] - x) < Math.abs(x - a[i]) ? i + 1 : i; }
// linear interpolation; null where a neighbour is missing (no bridging of data gaps)
function interp(ts, ys, t) { if (!ys || !ts.length) return null; const i = bsearch(ts, t);
  if (i >= ts.length - 1 || t <= ts[0]) { const v = ys[t <= ts[0] ? 0 : ts.length - 1]; return ok(v) ? v : null; }
  const a = ys[i], b = ys[i + 1]; if (!ok(a) || !ok(b)) return null;
  return a + (b - a) * clamp((t - ts[i]) / (ts[i + 1] - ts[i]), 0, 1); }
const finite = a => (a || []).filter(ok);
const mean = a => { const v = finite(a); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };
const pct = (a, p) => { const s = finite(a).sort((x, y) => x - y); return s.length ? s[Math.min(s.length - 1, Math.floor(p / 100 * s.length))] : null; };
const fmtT = t => { const s = Math.max(0, t), m = Math.floor(s / 60); return String(m).padStart(2, '0') + ':' + (s - m * 60).toFixed(1).padStart(4, '0'); };
const f0 = v => ok(v) ? Math.round(v).toString() : '—', f1 = v => ok(v) ? v.toFixed(1) : '—', f2 = v => ok(v) ? v.toFixed(2) : '—';
const sgn = v => ok(v) ? (v >= 0 ? '+' : '') + v.toFixed(1) : '—';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function niceStep(range, n) { const raw = range / Math.max(1, n), mag = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 5, 10]) if (m * mag >= raw) return m * mag; return 10 * mag; }
function fit(cv) { const d = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  if (cv.width !== Math.round(w * d) || cv.height !== Math.round(h * d)) { cv.width = Math.round(w * d); cv.height = Math.round(h * d); }
  const c = cv.getContext('2d'); c.setTransform(d, 0, 0, d, 0, 0); return { c, w, h }; }
function hexA(hex, a) { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; }
// one colour scale for scores everywhere: red -> amber -> green
function scoreColor(s) { if (!ok(s)) return '#59616d'; const st = [[0, [255, 92, 92]], [45, [242, 179, 61]], [70, [63, 208, 122]], [100, [63, 208, 122]]]; s = clamp(s, 0, 100);
  for (let i = 1; i < st.length; i++) if (s <= st[i][0]) { const [a, ca] = st[i - 1], [b, cb] = st[i], f = (s - a) / (b - a);
    return `rgb(${ca.map((c, k) => Math.round(c + (cb[k] - c) * f)).join(',')})`; } return 'rgb(63,208,122)'; }
// one colour per event type everywhere (plots, map, timeline, log, HUD)
const EV = { stop: { c: '#ff5c5c', n: 'Stop' }, slowdown: { c: '#4c8dff', n: 'Slowdown' }, change: { c: '#f2b33d', n: 'Walking change' },
  gps_artifact: { c: '#8a8f99', n: 'GPS artefact' }, hr_spike: { c: '#b3262e', n: 'HR spike' }, video: { c: '#b06cff', n: 'Video annotation' } };
let TH = {};
function refreshTheme() { const g = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  TH = { bg: g('--bg'), panel: g('--panel'), panel2: g('--panel2'), line: g('--line'), grid: g('--grid'), fg: g('--fg'), dim: g('--dim'),
    acc: g('--acc'), ok: g('--ok'), warn: g('--warn'), bad: g('--bad'), mag: g('--mag') }; }
function download(name, blob) { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }
const csvCell = v => v == null ? '' : /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v);
