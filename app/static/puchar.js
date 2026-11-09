import { $, h, facultyLabel, formatWarsawLong, pollLive, updateBars, categorySplit } from './common.js';

const fmt = (n) => Number(n).toLocaleString('pl-PL', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

/** Ranking: dlugosc slupka = WZ, podzial kolorow wg udzialu trzech kategorii w punktach (LD). */
function ranking(rows) {
  updateBars($('#cup-list'), rows.map((r, i) => ({
    key: r.code,
    rank: r.rank,
    label: facultyLabel(r),
    value: r.wz,
    countText: fmt(r.wz) + ' %',
    segments: [{ key: 'nowy', value: r.nowy || 0 }, { key: 'zarejestrowany', value: r.zarejestrowany || 0 }, { key: 'faktyczny', value: r.faktyczny || 0 }],
    first: i === 0 && r.wz > 0,
    aria: facultyLabel(r) + ': WZ ' + fmt(r.wz) + '% (punkty ' + r.registered + ': ' + (r.nowy || 0) + ' nowych, ' +
      (r.zarejestrowany || 0) + ' zarejestrowanych, ' + (r.faktyczny || 0) + ' faktycznych, studenci ' + r.students + ')',
    sub: h('span', {}, h('b', {}, r.registered), ' pkt (LD): ', categorySplit(r), ' · ',
      h('b', {}, r.students), ' studentów (LS)'),
  })), 'Ranking pojawi się, gdy organizatorzy uzupełnią liczby studentów i pojawią się punkty.');
}

function render(d) {
  ranking(d.ranking || []);
  const un = d.unranked || [];
  $('#unranked-section').hidden = un.length === 0;
  const list = $('#unranked-list');
  list.textContent = '';
  for (const u of un) {
    list.append(h('li', {}, h('span', {}, facultyLabel(u)),
      h('strong', {}, u.registered + ' (' + (u.nowy || 0) + ' nowych, ' + (u.zarejestrowany || 0) + ' zarejestrowanych, ' + (u.faktyczny || 0) + ' faktycznych)')));
  }
  $('#cup-source').textContent = d.source && String(d.source).trim() ? d.source : 'organizatorzy nie podali jeszcze źródła.';
  if (d.cup_deadline) $('#cup-deadline').textContent = formatWarsawLong(d.cup_deadline);
  $('#cup-closed').hidden = !d.cup_closed;
}

pollLive($('#cup-status'), render, '/api/stats/cup');
