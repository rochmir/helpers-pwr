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
  const token = storageGet('hp_game');
  if (token) headers['X-Game-Token'] = token;
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

export function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  return d.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
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

export function countMatches(a, b) {
  let n = 0;
  for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] === b[i]) n++;
  return n;
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

let tsScriptPromise = null;
function loadTurnstileScript() {
  if (window.turnstile) return Promise.resolve();
  if (!tsScriptPromise) {
    tsScriptPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
      s.async = true;
      s.addEventListener('load', () => resolve());
      s.addEventListener('error', () => { tsScriptPromise = null; reject(new Error('Nie udało się załadować zabezpieczenia antybotowego.')); });
      document.head.append(s);
    });
  }
  return tsScriptPromise;
}

/**
 * Renderuje widget Turnstile w containerEl.
 * Zwraca null, gdy Turnstile jest wylaczony (brak klucza), inaczej uchwyt:
 *   { getToken(): string|null, reset(): void }
 * Tokeny sa jednorazowe - wywolaj reset() po kazdym wyslaniu formularza.
 */
export async function loadTurnstile(containerEl) {
  const cfg = await getConfig();
  if (!cfg || !cfg.turnstile_site_key) return null;
  await loadTurnstileScript();
  let token = null;
  const widgetId = window.turnstile.render(containerEl, {
    sitekey: cfg.turnstile_site_key,
    callback: (t) => { token = t; },
    'expired-callback': () => { token = null; },
    'error-callback': () => { token = null; },
  });
  return {
    getToken: () => token,
    reset: () => { token = null; try { window.turnstile.reset(widgetId); } catch (e) { /* ignoruj */ } },
  };
}

/** Zwraca token do wyslania lub undefined; rzuca Error, gdy widget jest, a token jeszcze nie jest gotowy. */
export function requireToken(ts) {
  if (!ts) return undefined;
  const t = ts.getToken();
  if (!t) throw new Error('Poczekaj chwilę na weryfikację antybotową (pole powyżej) i spróbuj ponownie.');
  return t;
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
