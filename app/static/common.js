// Wspolne funkcje frontendu. Moduly ES; brak zaleznosci zewnetrznych.

// Ksztalty genotypu to ikony Tabler (webfont hostowany lokalnie): 0 trojkat, 1 kolo, 2 kwadrat, 3 gwiazdka.
export const SHAPE_ICONS = ['ti-triangle-filled', 'ti-circle-filled', 'ti-square-filled', 'ti-star-filled'];
export const SHAPE_NAMES = ['trójkąt', 'koło', 'kwadrat', 'gwiazdka'];

export function storageGet(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}
export function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* ignoruj */ }
}
export function storageRemove(key) {
  try { localStorage.removeItem(key); } catch (e) { /* ignoruj */ }
}

/** JSON fetch. Rzuca Error z polami status i detail. */
export async function api(method, path, body) {
  const headers = { Accept: 'application/json' };
  const opts = { method, headers, credentials: 'same-origin' };
  // Serwer wymaga JSON przy kazdym zapytaniu zmieniajacym dane (ochrona CSRF), takze bez tresci.
  if (body === undefined && method !== 'GET' && method !== 'HEAD') body = {};
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    const err = new Error('Brak połączenia z serwerem.');
    err.status = 0;
    err.detail = err.message;
    throw err;
  }
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch (e) { data = null; }
  }
  if (!res.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg || String(d)).join('; ');
    if (!detail) detail = 'Błąd serwera (' + res.status + ').';
    const err = new Error(String(detail));
    err.status = res.status;
    err.detail = String(detail);
    err.data = data;
    throw err;
  }
  return data;
}

/** Tworzy element: h('div', {class:'x', 'data-a':'b'}, 'tekst', child...) */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children) {
    if (c === null || c === undefined) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);

/** Pokazuje komunikat w elemencie (kind: 'error' | 'ok' | 'info'). Pusty tekst ukrywa. */
export function setMessage(el, text, kind = 'info') {
  if (!el) return;
  el.textContent = text || '';
  el.hidden = !text;
  el.className = el.className.replace(/\bmsg-(error|ok|info)\b/g, '').trim() + ' msg msg-' + kind;
}

export function formatDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  return d.toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' });
}

/** Ikona Tabler: icon('ti-download') -> <i class="ti ti-download" aria-hidden="true"></i> */
export function icon(name) {
  return h('i', { class: 'ti ' + name, 'aria-hidden': 'true' });
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Pojedynczy ksztalt genotypu (ikona + kolor + aria-label z polska nazwa). */
export function shapeEl(n, extraClass) {
  const idx = Number(n);
  const ok = idx >= 0 && idx < SHAPE_ICONS.length;
  return h('span', {
    class: 'shape shape-' + (ok ? idx : 'x') + (extraClass ? ' ' + extraClass : ''),
    role: 'img',
    'aria-label': ok ? SHAPE_NAMES[idx] : 'nieznany',
  }, ok ? icon(SHAPE_ICONS[idx]) : '?');
}

/** Data i godzina (do minuty) w strefie Europe/Warsaw z znacznika UTC serwera, np. "26.10.2026, 14:37".
 *  Celowo nie uzywa zegara ani strefy przegladarki. */
export function formatWarsaw(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat('pl-PL', {
    timeZone: 'Europe/Warsaw', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(d);
}

/** Data i godzina po polsku w strefie Europe/Warsaw z znacznika UTC serwera, np. "11 grudnia 2026, 16:00". */
export function formatWarsawLong(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const date = new Intl.DateTimeFormat('pl-PL', { timeZone: 'Europe/Warsaw', day: 'numeric', month: 'long', year: 'numeric' }).format(d);
  const time = new Intl.DateTimeFormat('pl-PL', { timeZone: 'Europe/Warsaw', hour: '2-digit', minute: '2-digit' }).format(d);
  return date + ', ' + time;
}

/** Rysuje genotyp jako komorki ksztaltow. mark: opcjonalny genotyp do porownania (klasy match / miss). */
export function renderGenotype(container, genotype, mark) {
  container.textContent = '';
  const g = String(genotype || '');
  for (let i = 0; i < g.length; i++) {
    container.append(shapeEl(g[i], mark ? (mark[i] === g[i] ? 'match' : 'miss') : ''));
  }
}

/** Etykieta wydzialu: "W4N - Wydzial ..."; wydzial "Inne" bez kodu. */
export function facultyLabel(f) {
  return f.code === 'INNE' ? f.name : f.code + ' - ' + f.name;
}

const MONTHS_GEN = ['stycznia', 'lutego', 'marca', 'kwietnia', 'maja', 'czerwca', 'lipca', 'sierpnia',
  'września', 'października', 'listopada', 'grudnia'];

function parseIsoDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
  return m ? { y: Number(m[1]), m: Number(m[2]) - 1, d: Number(m[3]) } : null;
}

/** Zakres dat po polsku: "3-7 listopada", "30 października - 2 listopada", "5 listopada"; rok tylko gdy inny niz biezacy. */
export function formatDateRange(from, to, nowYear = new Date().getFullYear()) {
  const a = parseIsoDate(from);
  const b = parseIsoDate(to);
  if (!a && !b) return '';
  const one = (p, withYear) => p.d + ' ' + MONTHS_GEN[p.m] + (withYear ? ' ' + p.y : '');
  if (a && !b) return 'od ' + one(a, a.y !== nowYear);
  if (!a && b) return 'do ' + one(b, b.y !== nowYear);
  const sameDay = a.y === b.y && a.m === b.m && a.d === b.d;
  if (sameDay) return one(a, a.y !== nowYear);
  const needYear = a.y !== nowYear || b.y !== nowYear;
  if (a.y === b.y && a.m === b.m) return a.d + '-' + one(b, needYear);
  if (a.y === b.y) return one(a, false) + ' - ' + one(b, needYear);
  return one(a, true) + ' - ' + one(b, true);
}

export function qrUrl(path) {
  return '/api/qr.svg?path=' + encodeURIComponent(path);
}

let configPromise = null;
export function getConfig() {
  if (!configPromise) {
    configPromise = api('GET', '/api/config').catch((e) => { configPromise = null; throw e; });
  }
  return configPromise;
}

/** Plynne doliczanie liczby w elemencie (ease-out). Bez animacji przy prefers-reduced-motion. */
export function countUp(el, from, to, ms = 1000, done) {
  const token = (el._countToken = (el._countToken || 0) + 1);
  const reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced || from === to) { el.textContent = to; if (done) done(to); return; }
  const t0 = performance.now();
  const step = (now) => {
    if (token !== el._countToken) return;
    const p = Math.min(1, (now - t0) / ms);
    const v = Math.round(from + (to - from) * (1 - Math.pow(1 - p, 3)));
    el.textContent = v;
    if (p < 1) requestAnimationFrame(step);
    else if (done) done(to);
  };
  requestAnimationFrame(step);
}

/** Liczba z doliczaniem tylko gdy wartosc sie zmienila. */
export function setCount(el, value) {
  const to = Number(value);
  if (!Number.isFinite(to)) { el.textContent = value ?? '-'; return; }
  const from = el.dataset.v === undefined ? 0 : Number(el.dataset.v);
  if (el.dataset.v !== undefined && from === to) return;
  el.dataset.v = to;
  countUp(el, from, to, 900);
}

/** Odswieza dane co 10 s z podanego endpointu i ustawia wskaznik "na zywo" w statusEl.
 *  render(dane) wypelnia strone; blad sieci pokazuje "Brak polaczenia" i ponawia. */
export function pollLive(statusEl, render, path = '/api/stats/live', ms = 10000) {
  const tick = async () => {
    try {
      render(await api('GET', path));
      statusEl.classList.remove('is-offline');
      statusEl.textContent = 'na żywo · ' + new Date().toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      statusEl.classList.add('is-offline');
      statusEl.textContent = 'Brak połączenia, ponawiam…';
    }
    setTimeout(tick, ms);
  };
  tick();
}

/** Tekst stoiska: "Budynek - Nazwa, 3-7 listopada" (lista w /graj). */
export function boothText(b) {
  const label = (b.building ? b.building + ' - ' : '') + b.name;
  const range = formatDateRange(b.date_from, b.date_to);
  return label + (range ? ', ' + range : '');
}

const barState = new WeakMap();

export const CATEGORIES = [['nowy', 'nowych'], ['zarejestrowany', 'zarejestrowanych'], ['faktyczny', 'faktycznych']];

/** Wykres slupkowy skumulowany: nowi (czerwony), zarejestrowani (zielony) i faktyczni (granatowy). Wiersze sa trwale
 *  i aktualizowane po kluczu, wiec slupki rosna od 0 przy pierwszym rysunku, a potem plynnie zmieniaja dlugosc.
 *  items: [{ key, rank (opcjonalnie), label, value (dlugosc slupka), countText,
 *            segments: [{ key: 'nowy'|'zarejestrowany'|'faktyczny', value }], aria, sub (wezel lub tekst) }] */
export function updateBars(listEl, items, emptyText) {
  let st = barState.get(listEl);
  if (!st) { st = { rows: new Map(), first: true }; barState.set(listEl, st); }
  if (!items.length) {
    listEl.textContent = '';
    st.rows.clear();
    listEl.append(h('li', { class: 'empty' }, emptyText));
    return;
  }
  if (st.rows.size === 0) listEl.textContent = '';
  const max = Math.max(...items.map((it) => it.value), 0.0001);
  const seen = new Set();
  items.forEach((it, i) => {
    seen.add(it.key);
    let row = st.rows.get(it.key);
    if (!row) {
      const segs = {};
      for (const [k] of CATEGORIES) segs[k] = h('span', { class: 'seg seg-' + k });
      const group = h('span', { class: 'seg-group' }, ...CATEGORIES.map(([k]) => segs[k]));
      const rank = it.rank === undefined ? null : h('span', { class: 'bar-rank' });
      const name = h('span', { class: 'bar-label' });
      const track = h('div', { class: 'stack', role: 'img' }, group);
      const count = h('strong', { class: 'bar-count' });
      const sub = h('span', { class: 'bar-sub' });
      const el = h('li', { class: 'bar-row' }, rank, name, track, h('span', { class: 'bar-num' }, count), sub);
      row = { el, group, segs, rank, name, track, count, sub };
      st.rows.set(it.key, row);
    }
    if (row.rank) row.rank.textContent = it.rank;
    row.name.textContent = it.label;
    row.el.classList.toggle('is-first', it.first === true);
    row.track.setAttribute('aria-label', it.aria);
    row.count.textContent = it.countText;
    row.sub.textContent = '';
    row.sub.append(it.sub);
    const values = {};
    for (const seg of it.segments || []) values[seg.key] = seg.value;
    const sum = CATEGORIES.reduce((a, [k]) => a + (values[k] || 0), 0);
    const apply = () => {
      row.group.style.width = (it.value / max * 100) + '%';
      for (const [k] of CATEGORIES) row.segs[k].style.width = (sum ? (values[k] || 0) / sum * 100 : 0) + '%';
    };
    if (st.first) {
      row.group.style.width = '0%';
      requestAnimationFrame(() => requestAnimationFrame(apply));
    } else apply();
    if (listEl.children[i] !== row.el) listEl.insertBefore(row.el, listEl.children[i] || null);
  });
  for (const [key, row] of st.rows) {
    if (!seen.has(key)) { row.el.remove(); st.rows.delete(key); }
  }
  st.first = false;
}

/** Podpis z rozbiciem na trzy kategorie: "2 nowych · 1 zarejestrowanych · 0 faktycznych". */
export function categorySplit(r) {
  const parts = [];
  CATEGORIES.forEach(([k, label], i) => {
    if (i) parts.push(' · ');
    parts.push(h('span', { class: 'split-' + k }, h('b', {}, r[k] || 0), ' ' + label));
  });
  return h('span', {}, ...parts);
}

/** Tabele `.table`: każda komórka dostaje data-label z nagłówka kolumny (na telefonie wiersze są kartami). */
function labelTable(table) {
  const heads = [...table.querySelectorAll('thead th')].map((th) => th.textContent.trim());
  for (const tr of table.querySelectorAll('tbody tr')) {
    [...tr.children].forEach((td, i) => {
      if (td.tagName === 'TD' && heads[i] && td.dataset.label !== heads[i]) td.dataset.label = heads[i];
    });
  }
}
function watchTables() {
  for (const table of document.querySelectorAll('table.table')) {
    labelTable(table);
    new MutationObserver(() => labelTable(table)).observe(table, { childList: true, subtree: true });
  }
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watchTables);
else watchTables();
