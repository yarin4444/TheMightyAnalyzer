// ---------------------------------------------------------------- data + master clock / shared state
const DATA = JSON.parse(document.getElementById('walk-data').textContent);
const EXTRAS = JSON.parse(document.getElementById('walk-extras').textContent);
const META = DATA.meta, SIG = DATA.signals, SUM = DATA.summary, CFG = DATA.config, SRC = DATA.sources;
// time axis = sensor time t (s since the first accelerometer sample); the walk spans [T0, T1]
const T0 = META.t0, T1 = META.t1, D = Math.max(1, T1 - T0);
const WINS = DATA.windows || [], WIN_C = WINS.map(w => (w.t0 + w.t1) / 2);
const WSTEP = (CFG.window_s || 5) * (1 - (CFG.overlap ?? .5)) || 2.5;
const HAS_OWI = WINS.some(w => ok(w.owi));
const HAS_HR = !!(SIG.hr && SIG.hr.some(ok));
const TRACK = DATA.track;
const winAt = t => WINS.length ? WINS[nearestIdx(WIN_C, t)] : null;
const winIdx = t => WINS.length ? nearestIdx(WIN_C, t) : -1;
const sigAt = (k, t) => interp(SIG.t, SIG[k], t);
const activeEvents = t => DATA.events.filter(e => t >= e.t0 && t <= e.t1);
const MOD_KEYS = ['msi', 'eei', 'pci'];
const MOD_AVAIL = { msi: !!CFG.modules.MSI?.available, eei: !!CFG.modules.EEI?.available, pci: !!CFG.modules.PCI?.available };
const MOD_MEAN = { msi: SUM.module_means?.MSI, eei: SUM.module_means?.EEI, pci: SUM.module_means?.PCI };
const STEP_RATE_ALL = DATA.steps_t.length / D;

const S = { t: T0, playing: false, rate: 1, view: { t0: T0, t1: T1 }, hoverT: null, tab: 'plots', dirty: true, logCur: null };
const SEEK_HOOKS = [];
function setView(t0, t1) { const span = clamp(t1 - t0, 5, D); t0 = clamp(t0, T0, T1 - span); S.view = { t0, t1: t0 + span }; S.dirty = true; }
function keepInView() { const { t0, t1 } = S.view; if (S.t < t0 || S.t > t1) setView(S.t - (t1 - t0) * .1, S.t + (t1 - t0) * .9); }
// every user seek goes through here; the video follows via SEEK_HOOKS
function seek(t) { S.t = clamp(t, T0, T1); keepInView(); S.dirty = true; SEEK_HOOKS.forEach(f => f(S.t)); }
