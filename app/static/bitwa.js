import { api, $, h, facultyLabel } from './common.js';

const fmt = (n) => Number(n).toLocaleString('pl-PL', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

function bars(listEl, rows) {
  listEl.textContent = '';
  if (!rows.length) {
    listEl.append(h('li', { class: 'empty' }, 'Ranking pojawi się, gdy organizatorzy uzupełnią liczby studentów i pojawią się rejestracje.'));
    return;
  }
  const max = Math.max(...rows.map((r) => r.per_1000), 0.01);
  for (const r of rows) {
    const seg = h('span', { class: 'seg seg-potential' });
    seg.style.width = (r.per_1000 / max * 100) + '%';
    const track = h('div', { class: 'stack', role: 'img',
      'aria-label': facultyLabel(r) + ': ' + fmt(r.per_1000) + ' rejestracji na 1000 studentów' }, seg);
    listEl.append(h('li', { class: 'bar-row' },
      h('span', { class: 'bar-label' }, h('span', { class: 'rank' }, r.rank + '.'), facultyLabel(r)),
      track,
      h('span', { class: 'bar-count' }, fmt(r.per_1000)),
      h('span', { class: 'bar-sub' }, r.registered + ' rejestracji, ' + r.students + ' studentów')));
  }
}

function render(d) {
  const ranking = d.ranking || [];
  bars($('#battle-list'), ranking);
  const body = $('#battle-body');
  body.textContent = '';
  for (const r of ranking) {
    body.append(h('tr', {}, h('td', {}, r.rank), h('td', {}, facultyLabel(r)), h('td', {}, r.registered),
      h('td', {}, r.students), h('td', {}, fmt(r.per_1000))));
  }
  if (!ranking.length) body.append(h('tr', {}, h('td', { colspan: 5 }, 'Brak danych')));
  const un = d.unranked || [];
  $('#unranked-section').hidden = un.length === 0;
  const list = $('#unranked-list');
  list.textContent = '';
  for (const u of un) list.append(h('li', {}, h('span', {}, facultyLabel(u)), h('strong', {}, u.registered)));
  $('#battle-source').textContent = d.source && String(d.source).trim() ? d.source : 'organizatorzy nie podali jeszcze źródła.';
}

async function refresh() {
  try {
    render(await api('GET', '/api/stats/battle'));
    $('#battle-status').textContent = 'Odświeżane co 10 s. Ostatnia aktualizacja: ' + new Date().toLocaleTimeString('pl-PL');
  } catch (e) {
    $('#battle-status').textContent = 'Brak połączenia, próbuję ponownie…';
  }
  setTimeout(refresh, 10000);
}

refresh();
