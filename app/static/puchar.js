import { api, $, h, facultyLabel, formatWarsawLong } from './common.js';

const fmt = (n) => Number(n).toLocaleString('pl-PL', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

function bars(listEl, rows) {
  listEl.textContent = '';
  if (!rows.length) {
    listEl.append(h('li', { class: 'empty' }, 'Ranking pojawi się, gdy organizatorzy uzupełnią liczby studentów i pojawią się punkty.'));
    return;
  }
  const max = Math.max(...rows.map((r) => r.wz), 0.01);
  for (const r of rows) {
    const seg = h('span', { class: 'seg seg-potential' });
    seg.style.width = (r.wz / max * 100) + '%';
    const track = h('div', { class: 'stack', role: 'img',
      'aria-label': facultyLabel(r) + ': WZ ' + fmt(r.wz) + ' (punkty ' + r.registered + ', studenci ' + r.students + ')' }, seg);
    listEl.append(h('li', { class: 'bar-row' },
      h('span', { class: 'bar-label' }, h('span', { class: 'rank' }, r.rank + '.'), facultyLabel(r)),
      track,
      h('span', { class: 'bar-count' }, fmt(r.wz)),
      h('span', { class: 'bar-sub' }, r.registered + ' pkt (LD), ' + r.students + ' studentów (LS)')));
  }
}

function render(d) {
  const ranking = d.ranking || [];
  bars($('#cup-list'), ranking);
  const body = $('#cup-body');
  body.textContent = '';
  for (const r of ranking) {
    body.append(h('tr', {}, h('td', {}, r.rank), h('td', {}, facultyLabel(r)), h('td', {}, r.registered),
      h('td', {}, r.students), h('td', {}, fmt(r.wz))));
  }
  if (!ranking.length) body.append(h('tr', {}, h('td', { colspan: 5 }, 'Brak danych')));
  const un = d.unranked || [];
  $('#unranked-section').hidden = un.length === 0;
  const list = $('#unranked-list');
  list.textContent = '';
  for (const u of un) list.append(h('li', {}, h('span', {}, facultyLabel(u)), h('strong', {}, u.registered)));
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
