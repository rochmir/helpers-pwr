import { api, $, h, facultyLabel, countUp } from './common.js';

/** Liczba z doliczaniem tylko gdy wartosc sie zmienila. */
function setCount(el, value) {
  const to = Number(value);
  if (!Number.isFinite(to)) { el.textContent = value ?? '-'; return; }
  const from = el.dataset.v === undefined ? 0 : Number(el.dataset.v);
  if (el.dataset.v !== undefined && from === to) return;
  el.dataset.v = to;
  countUp(el, from, to, 900);
}

const rowsByKey = new Map();
let firstRender = true;

function makeRow() {
  const potential = h('span', { class: 'seg seg-potential' });
  const actual = h('span', { class: 'seg seg-actual' });
  const rank = h('span', { class: 'bar-rank' });
  const name = h('span', { class: 'bar-label' });
  const track = h('div', { class: 'stack', role: 'img' }, potential, actual);
  const count = h('strong', { class: 'bar-count' });
  const split = h('span', { class: 'bar-split' });
  const el = h('li', { class: 'bar-row' }, rank, name, track, h('span', { class: 'bar-num' }, count, split));
  return { el, potential, actual, rank, name, track, count, split };
}

/** Wykres skumulowany: potencjalni (czerwony) + faktyczni (granatowy). Wiersze aktualizowane po kodzie wydzialu. */
function bars(listEl, rows) {
  if (!rows.length) {
    listEl.textContent = '';
    rowsByKey.clear();
    listEl.append(h('li', { class: 'empty' }, 'Brak danych'));
    return;
  }
  if (rowsByKey.size === 0) listEl.textContent = '';
  const max = Math.max(...rows.map((r) => r.total), 1);
  const seen = new Set();
  rows.forEach((r, i) => {
    const key = r.code || facultyLabel(r);
    seen.add(key);
    let row = rowsByKey.get(key);
    if (!row) { row = makeRow(); rowsByKey.set(key, row); }
    row.rank.textContent = i + 1;
    row.name.textContent = facultyLabel(r);
    row.el.classList.toggle('is-first', i === 0 && r.total > 0);
    row.track.setAttribute('aria-label', facultyLabel(r) + ': potencjalni ' + r.potential + ', faktyczni ' + r.actual + ', razem ' + r.total);
    row.count.textContent = r.total;
    row.split.textContent = 'P ' + r.potential + ' · F ' + r.actual;
    const apply = () => {
      row.potential.style.width = (r.potential / max * 100) + '%';
      row.actual.style.width = (r.actual / max * 100) + '%';
    };
    if (firstRender) {
      row.potential.style.width = '0%';
      row.actual.style.width = '0%';
      requestAnimationFrame(() => requestAnimationFrame(apply));
    } else apply();
    if (listEl.children[i] !== row.el) listEl.insertBefore(row.el, listEl.children[i] || null);
  });
  for (const [key, row] of rowsByKey) {
    if (!seen.has(key)) { row.el.remove(); rowsByKey.delete(key); }
  }
  firstRender = false;
}

function booths(listEl, rows) {
  listEl.textContent = '';
  if (!rows.length) { listEl.append(h('li', { class: 'empty' }, 'Brak danych')); return; }
  for (const b of rows) {
    listEl.append(h('li', {},
      h('span', { class: 'booth-name' }, b.name),
      h('span', { class: 'booth-figs' },
        h('span', {}, h('b', {}, b.registered), ' zarejestrowanych'),
        h('span', {}, h('b', {}, b.matches_count), ' trafień 10/10'),
        h('span', {}, h('b', {}, b.rolls_count), ' losowań'))));
  }
}

async function refresh() {
  const status = $('#stats-status');
  try {
    const s = await api('GET', '/api/stats/live');
    setCount($('#total'), s.total);
    bars($('#faculties-list'), s.faculties || []);
    booths($('#booths-list'), s.booths || []);
    const g = s.game || {};
    setCount($('#g-players'), g.players ?? '-');
    setCount($('#g-rolls'), g.rolls ?? '-');
    setCount($('#g-matches'), g.matches ?? '-');
    status.classList.remove('is-offline');
    status.textContent = 'na żywo · ' + new Date().toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
  } catch (e) {
    status.classList.add('is-offline');
    status.textContent = 'Brak połączenia, ponawiam…';
  }
  setTimeout(refresh, 10000);
}

refresh();
