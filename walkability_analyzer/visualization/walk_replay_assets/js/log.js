// ---------------------------------------------------------------- event log (sortable, filterable, follows the playhead)
const LOGF = new Set(Object.keys(EV));
const LOG_SORT = { key: 't0', dir: 1 };
const LOG_COLS = [['#', null], ['start', 't0'], ['end', 't1'], ['dur [s]', 'dur'], ['type', 'type'], ['details', 'label']];
function buildLog() {
  $('#logFilters').innerHTML = 'show: ' + Object.keys(EV).map(k => `<label><input type="checkbox" data-f="${k}" checked><span class="dot" style="background:${EV[k].c}"></span>${EV[k].n} (${DATA.events.filter(e => e.type === k).length})</label>`).join('') +
    '<span class="hint" style="margin-left:auto">click a row → seek (3 s pre-roll) · click a header to sort</span>';
  $('#logFilters').addEventListener('change', e => { const k = e.target.dataset.f; if (!k) return; e.target.checked ? LOGF.add(k) : LOGF.delete(k); renderLog(); });
  renderLog(); }
function renderLog() { const val = (e, k) => k === 'dur' ? e.t1 - e.t0 : e[k];
  const rows = DATA.events.map((e, i) => ({ e, i })).filter(r => LOGF.has(r.e.type))
    .sort((a, b) => { const x = val(a.e, LOG_SORT.key), y = val(b.e, LOG_SORT.key); return (x > y ? 1 : x < y ? -1 : 0) * LOG_SORT.dir; });
  $('#logTable').innerHTML = '<tr>' + LOG_COLS.map(([n, k]) => `<th data-k="${k || ''}">${n}${LOG_SORT.key === k ? (LOG_SORT.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('') + '</tr>' + rows.map(({ e, i }) =>
    `<tr data-i="${i}" style="color:${EV[e.type].c}"><td>${i + 1}</td><td>${e.t0.toFixed(1)}</td><td>${e.t1.toFixed(1)}</td><td>${(e.t1 - e.t0).toFixed(1)}</td><td><span class="dot" style="background:${EV[e.type].c}"></span>${EV[e.type].n}</td><td class="det">${esc(e.label)}</td></tr>`).join('');
  S.logCur = null; }
$('#logTable').addEventListener('click', e => { const th = e.target.closest('th[data-k]'); if (th && th.dataset.k) { const k = th.dataset.k; LOG_SORT.dir = LOG_SORT.key === k ? -LOG_SORT.dir : 1; LOG_SORT.key = k; renderLog(); return; }
  const tr = e.target.closest('tr[data-i]'); if (tr) seek(DATA.events[+tr.dataset.i].t0 - 3); });
function updateLogCursor() { if (S.tab !== 'log') return; let cur = -1, best = -Infinity;
  DATA.events.forEach((e, i) => { if (LOGF.has(e.type) && e.type !== 'video' && e.t0 <= S.t && e.t0 > best) { best = e.t0; cur = i; } });
  if (cur === S.logCur) return; S.logCur = cur; document.querySelectorAll('#logTable tr.cur').forEach(r => r.classList.remove('cur'));
  const tr = document.querySelector(`#logTable tr[data-i="${cur}"]`); if (tr) { tr.classList.add('cur'); tr.scrollIntoView({ block: 'nearest' }); } }
function eventsCsv() { const keys = [...new Set(DATA.events.flatMap(e => Object.keys(e.details || {})))];
  return ['type,t0,t1,duration_s,label,' + keys.join(',')].concat(DATA.events.map(e => [e.type, e.t0, e.t1, (e.t1 - e.t0).toFixed(2), e.label, ...keys.map(k => e.details?.[k])].map(csvCell).join(','))).join('\n'); }
