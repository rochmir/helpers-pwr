import { $, h, facultyLabel, setCount, pollLive, updateBars, categorySplit } from './common.js';

/** Wykres punktow wydzialow (kolejnosc slownika, bez rankingu): nowi, zarejestrowani i faktyczni. */
function faculties(rows) {
  updateBars($('#faculties-list'), rows.map((r) => ({
    key: r.code || facultyLabel(r),
    label: facultyLabel(r),
    value: r.count,
    countText: r.count,
    segments: [{ key: 'nowy', value: r.nowy || 0 }, { key: 'zarejestrowany', value: r.zarejestrowany || 0 }, { key: 'faktyczny', value: r.faktyczny || 0 }],
    aria: facultyLabel(r) + ': ' + r.count + ' pkt (' + (r.nowy || 0) + ' nowych, ' + (r.zarejestrowany || 0) +
      ' zarejestrowanych, ' + (r.faktyczny || 0) + ' faktycznych)',
    sub: categorySplit(r),
  })), 'Brak danych');
}

function booths(listEl, rows) {
  listEl.textContent = '';
  if (!rows.length) { listEl.append(h('li', { class: 'empty' }, 'Brak danych')); return; }
  for (const b of rows) {
    listEl.append(h('li', {},
      h('span', { class: 'booth-name' }, b.name),
      h('span', { class: 'booth-figs' },
        h('span', {}, h('b', {}, b.registered), ' głosów w Pucharze'),
        h('span', { class: 'split-nowy' }, h('b', {}, b.nowy || 0), ' nowych'),
        h('span', { class: 'split-zarejestrowany' }, h('b', {}, b.zarejestrowany || 0), ' zarejestrowanych'),
        h('span', { class: 'split-faktyczny' }, h('b', {}, b.faktyczny || 0), ' faktycznych'),
        h('span', {}, h('b', {}, b.matches_count), ' trafień 10/10'),
        h('span', {}, h('b', {}, b.rolls_count), ' prób'))));
  }
}

pollLive($('#stats-status'), (s) => {
  setCount($('#total'), s.total);
  setCount($('#total-n'), s.total_nowy);
  setCount($('#total-z'), s.total_zarejestrowany);
  setCount($('#total-f'), s.total_faktyczny);
  faculties(s.faculties || []);
  booths($('#booths-list'), s.booths || []);
  const g = s.game || {};
  setCount($('#g-players'), g.players ?? '-');
  setCount($('#g-rolls'), g.rolls ?? '-');
  setCount($('#g-matches'), g.matches ?? '-');
});
