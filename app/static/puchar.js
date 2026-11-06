import { $, h, facultyLabel, formatWarsawLong, pollLive, updateBars } from './common.js';

const fmt = (n) => Number(n).toLocaleString('pl-PL', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

/** Po „w tym”: 1 faktyczny dawca, 2 i więcej faktycznych dawców. */
const actualText = (n) => (n === 1 ? ' faktyczny dawca' : ' faktycznych dawców');

/** Ranking: dlugosc slupka = WZ, podzial kolorow wg udzialu nowych i faktycznych w punktach (LD). */
function ranking(rows) {
  updateBars($('#cup-list'), rows.map((r, i) => {
    const actual = r.actual || 0;
    return {
      key: r.code,
      rank: r.rank,
      label: facultyLabel(r),
      value: r.wz,
      countText: fmt(r.wz) + ' %',
      potential: r.registered - actual,
      actual,
      first: i === 0 && r.wz > 0,
      aria: facultyLabel(r) + ': WZ ' + fmt(r.wz) + '% (punkty ' + r.registered + ', w tym faktyczni dawcy ' + actual +
        ', studenci ' + r.students + ')',
      sub: h('span', {}, h('b', {}, r.registered), ' pkt (LD), w tym ',
        h('span', { class: 'split-actual' }, h('b', {}, actual), actualText(actual)), ' · ',
        h('b', {}, r.students), ' studentów (LS)'),
    };
  }), 'Ranking pojawi się, gdy organizatorzy uzupełnią liczby studentów i pojawią się punkty.');
}

function render(d) {
  ranking(d.ranking || []);
  const un = d.unranked || [];
  $('#unranked-section').hidden = un.length === 0;
  const list = $('#unranked-list');
  list.textContent = '';
  for (const u of un) list.append(h('li', {}, h('span', {}, facultyLabel(u)), h('strong', {}, u.registered + ' (w tym faktycznych: ' + (u.actual || 0) + ')')));
  $('#cup-source').textContent = d.source && String(d.source).trim() ? d.source : 'organizatorzy nie podali jeszcze źródła.';
  if (d.cup_deadline) $('#cup-deadline').textContent = formatWarsawLong(d.cup_deadline);
  $('#cup-closed').hidden = !d.cup_closed;
}

pollLive($('#cup-status'), render, '/api/stats/cup');
