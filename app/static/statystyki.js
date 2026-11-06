import { $, h, facultyLabel, setCount, pollLive, updateBars } from './common.js';

/** Wykres punktow wydzialow (kolejnosc slownika, bez rankingu): nowi czerwony + faktyczni granatowy. */
function faculties(rows) {
  updateBars($('#faculties-list'), rows.map((r) => {
    const actual = r.actual || 0;
    return {
      key: r.code || facultyLabel(r),
      label: facultyLabel(r),
      value: r.count,
      countText: r.count,
      potential: r.count - actual,
      actual,
      aria: facultyLabel(r) + ': ' + r.count + ' pkt, w tym faktyczni dawcy ' + actual,
      sub: h('span', {}, h('span', { class: 'split-potential' }, h('b', {}, r.count - actual), ' potencjalnych'), ' · ',
        h('span', { class: 'split-actual' }, h('b', {}, actual), ' faktycznych dawców')),
    };
  }), 'Brak danych');
}

function booths(listEl, rows) {
  listEl.textContent = '';
  if (!rows.length) { listEl.append(h('li', { class: 'empty' }, 'Brak danych')); return; }
  for (const b of rows) {
    listEl.append(h('li', {},
      h('span', { class: 'booth-name' }, b.name),
      h('span', { class: 'booth-figs' },
        h('span', {}, h('b', {}, b.registered), ' wpisanych tokenów rejestracyjnych'),
        h('span', { class: 'split-actual' }, h('b', {}, b.actual || 0), ' w tym faktycznych dawców'),
        h('span', {}, h('b', {}, b.matches_count), ' trafień 10/10'),
        h('span', {}, h('b', {}, b.rolls_count), ' prób'))));
  }
}

pollLive($('#stats-status'), (s) => {
  setCount($('#total'), s.total);
  setCount($('#total-p'), s.total_potential);
  setCount($('#total-a'), s.total_actual);
  faculties(s.faculties || []);
  booths($('#booths-list'), s.booths || []);
  const g = s.game || {};
  setCount($('#g-players'), g.players ?? '-');
  setCount($('#g-rolls'), g.rolls ?? '-');
  setCount($('#g-matches'), g.matches ?? '-');
});
