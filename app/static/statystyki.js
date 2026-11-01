import { api, $, h, facultyLabel } from './common.js';

/** Wykres punktow wydzialow (kolejnosc slownika, bez rankingu). */
function bars(listEl, rows) {
  listEl.textContent = '';
  if (!rows.length) {
    listEl.append(h('li', { class: 'empty' }, 'Brak danych'));
    return;
  }
  const max = Math.max(...rows.map((r) => r.count), 1);
  for (const r of rows) {
    const actual = r.actual || 0;
    const potential = r.count - actual;
    const group = h('span', { class: 'seg-group' });
    group.style.width = (r.count / max * 100) + '%';
    if (potential > 0) {
      const p = h('span', { class: 'seg seg-potential' });
      p.style.width = (potential / r.count * 100) + '%';
      group.append(p);
    }
    if (actual > 0) {
      const a = h('span', { class: 'seg seg-actual' });
      a.style.width = (actual / r.count * 100) + '%';
      group.append(a);
    }
    const track = h('div', { class: 'stack', role: 'img',
      'aria-label': facultyLabel(r) + ': ' + r.count + ' pkt, w tym faktyczni dawcy ' + actual }, group);
    listEl.append(h('li', { class: 'bar-row' },
      h('span', { class: 'bar-label' }, facultyLabel(r)), track, h('span', { class: 'bar-count' }, r.count),
      h('span', { class: 'bar-sub' }, actualText(actual))));
  }
}

/** Po „w tym”: 1 faktyczny dawca, 2 i więcej faktycznych dawców. */
const actualText = (n) => 'w tym ' + n + (n === 1 ? ' faktyczny dawca' : ' faktycznych dawców');

function facultyTable(rows) {
  const body = $('#faculties-body');
  body.textContent = '';
  for (const r of rows) body.append(h('tr', {}, h('td', {}, facultyLabel(r)), h('td', {}, r.count), h('td', {}, r.actual || 0)));
}

async function refresh() {
  try {
    const s = await api('GET', '/api/stats/live');
    $('#total').textContent = s.total;
    $('#total-kinds').textContent = 'Wpisane tokeny wg typu: nowi dawcy ' + s.total_potential + ', dawcy faktyczni ' + s.total_actual + '.';
    bars($('#faculties-list'), s.faculties || []);
    facultyTable(s.faculties || []);
    const body = $('#booths-body');
    body.textContent = '';
    for (const b of s.booths || []) {
      body.append(h('tr', {}, h('td', {}, b.name), h('td', {}, b.registered), h('td', {}, b.actual || 0), h('td', {}, b.matches_count), h('td', {}, b.rolls_count)));
    }
    if (!(s.booths || []).length) body.append(h('tr', {}, h('td', { colspan: 5 }, 'Brak danych')));
    const g = s.game || {};
    $('#g-players').textContent = g.players ?? '-';
    $('#g-rolls').textContent = g.rolls ?? '-';
    $('#g-matches').textContent = g.matches ?? '-';
    $('#stats-status').textContent = 'Odświeżane co 10 s. Ostatnia aktualizacja: ' + new Date().toLocaleTimeString('pl-PL');
  } catch (e) {
    $('#stats-status').textContent = 'Brak połączenia, próbuję ponownie…';
  }
  setTimeout(refresh, 10000);
}

refresh();
