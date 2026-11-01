import { api, $, h, facultyLabel, formatWarsawLong } from './common.js';

const fmt = (n) => Number(n).toLocaleString('pl-PL', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

/** Po „w tym”: 1 faktycznego dawcy, 2 i więcej faktycznych dawców. */
const actualText = (n) => 'w tym ' + n + (n === 1 ? ' faktycznego dawcy' : ' faktycznych dawców');

function bars(listEl, rows) {
  listEl.textContent = '';
  if (!rows.length) {
    listEl.append(h('li', { class: 'empty' }, 'Ranking pojawi się, gdy organizatorzy uzupełnią liczby studentów i pojawią się punkty.'));
    return;
  }
  const max = Math.max(...rows.map((r) => r.wz), 0.01);
  for (const r of rows) {
    const actual = r.actual || 0;
    const potential = r.registered - actual;
    const group = h('span', { class: 'seg-group' });
    group.style.width = (r.wz / max * 100) + '%';
    if (potential > 0) {
      const p = h('span', { class: 'seg seg-potential' });
      p.style.width = (potential / r.registered * 100) + '%';
      group.append(p);
    }
    if (actual > 0) {
      const a = h('span', { class: 'seg seg-actual' });
      a.style.width = (actual / r.registered * 100) + '%';
      group.append(a);
    }
    const track = h('div', { class: 'stack', role: 'img',
      'aria-label': facultyLabel(r) + ': WZ ' + fmt(r.wz) + ' (punkty ' + r.registered + ', w tym faktyczni dawcy ' + actual +
        ', studenci ' + r.students + ')' }, group);
    listEl.append(h('li', { class: 'bar-row' },
      h('span', { class: 'bar-label' }, h('span', { class: 'rank' }, r.rank + '.'), facultyLabel(r)),
      track,
      h('span', { class: 'bar-count' }, fmt(r.wz)),
      h('span', { class: 'bar-sub' }, r.registered + ' pkt (LD), ' + actualText(actual) + ', ' + r.students + ' studentów (LS)')));
  }
}

function render(d) {
  const ranking = d.ranking || [];
  bars($('#cup-list'), ranking);
  const body = $('#cup-body');
  body.textContent = '';
  for (const r of ranking) {
    body.append(h('tr', {}, h('td', {}, r.rank), h('td', {}, facultyLabel(r)), h('td', {}, r.registered),
      h('td', {}, r.actual || 0), h('td', {}, r.students), h('td', {}, fmt(r.wz))));
  }
  if (!ranking.length) body.append(h('tr', {}, h('td', { colspan: 6 }, 'Brak danych')));
  const un = d.unranked || [];
  $('#unranked-section').hidden = un.length === 0;
  const list = $('#unranked-list');
  list.textContent = '';
  for (const u of un) list.append(h('li', {}, h('span', {}, facultyLabel(u)), h('strong', {}, u.registered + ' (w tym faktycznych: ' + (u.actual || 0) + ')')));
  $('#cup-source').textContent = d.source && String(d.source).trim() ? d.source : 'organizatorzy nie podali jeszcze źródła.';
  if (d.cup_deadline) $('#cup-deadline').textContent = formatWarsawLong(d.cup_deadline);
  $('#cup-closed').hidden = !d.cup_closed;
}

async function refresh() {
  try {
    render(await api('GET', '/api/stats/cup'));
    $('#cup-status').textContent = 'Odświeżane co 10 s. Ostatnia aktualizacja: ' + new Date().toLocaleTimeString('pl-PL');
  } catch (e) {
    $('#cup-status').textContent = 'Brak połączenia, próbuję ponownie…';
  }
  setTimeout(refresh, 10000);
}

refresh();
