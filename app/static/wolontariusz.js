// Czesc panelu dla wolontariusza (liczniki stoiska i jednorazowy kod QR do Pucharu). Logowanie i wybor stoiska robi login.js.
import { api, $, setMessage, qrUrl } from './common.js';

const msg = $('#panel-msg');
const CATS = {
  nowy: { label: 'Nowy dawca', icon: 'ti-user-plus' },
  zarejestrowany: { label: 'Zarejestrowany dawca', icon: 'ti-id-badge' },
  faktyczny: { label: 'Faktyczny dawca', icon: 'ti-droplet' },
  post: { label: 'Post / story (+5 prób)', icon: 'ti-brand-instagram' },
};
// Stan kodu -> wyglad plakietki, naklejki na kodzie i to, czy kod jest przyciemniony.
const STATES = {
  active: { badge: 'Czeka na zeskanowanie', icon: 'ti-clock', kind: 'wait', dim: false },
  scanned: { badge: 'Zeskanowano, student wybiera wydział', icon: 'ti-scan', kind: 'wait', dim: true,
    overlay: 'Zeskanowano: student wybiera wydział' },
  voted: { badge: 'Zużyty, głos oddany', icon: 'ti-circle-check', kind: 'ok', dim: true, overlay: 'Zużyty: głos oddany' },
  granted: { badge: 'Zużyty, przyznano +5 prób', icon: 'ti-circle-check', kind: 'ok', dim: true,
    overlay: 'Zużyty: przyznano +5 prób' },
  revoked: { badge: 'Nieaktualny', icon: 'ti-ban', kind: 'off', dim: true, overlay: 'Nieaktualny' },
};
const POLL_MS = 2000;
const POLL_MAX_MS = 15 * 60 * 1000; // tyle czekamy na głos po zeskanowaniu
const FINAL = new Set(['voted', 'granted', 'revoked']);

let refreshTimer = null;
let pollTimer = null;
let code = null; // { id, status, scannedAt }
let ctx = { role: 'volunteer', boothId: '' };
let wired = false;
let cupClosed = false;

const radios = () => [...document.querySelectorAll('input[name="qr-cat"]')];
const meUrl = () => '/api/volunteer/me' + (ctx.role === 'admin' && ctx.boothId ? '?booth_id=' + encodeURIComponent(ctx.boothId) : '');
const selectedCategory = () => {
  const r = document.querySelector('input[name="qr-cat"]:checked');
  return r ? r.value : '';
};

function syncShowButton() {
  $('#qr-show').disabled = !selectedCategory();
}

function clearSelection() {
  for (const r of radios()) r.checked = false;
  syncShowButton();
}

async function refresh() {
  clearTimeout(refreshTimer);
  if (!ctx.boothId) return;
  try {
    const me = await api('GET', meUrl());
    $('#vol-booth-name').textContent = me.booth ? me.booth.name : '';
    $('#booth-screen-link').href = me.booth ? '/stoisko/' + encodeURIComponent(me.booth.id) : '/';
    $('#c-nowy').textContent = me.registered_nowy ?? 0;
    $('#c-zarejestrowany').textContent = me.registered_zarejestrowany ?? 0;
    $('#c-faktyczny').textContent = me.registered_faktyczny ?? 0;
    $('#c-matches').textContent = me.matches_count ?? 0;
    $('#c-rolls').textContent = me.rolls_count ?? 0;
    applyClosed(!!me.cup_closed, me.cup_closed_message);
    refreshTimer = setTimeout(refresh, 15000);
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    setMessage(msg, e.detail || e.message, 'error');
    refreshTimer = setTimeout(refresh, 15000);
  }
}

/** Po terminie Pucharu trzy kategorie głosu są wyłączone; „post” zostaje. */
function applyClosed(closed, text) {
  cupClosed = closed;
  const note = $('#cup-closed-note');
  note.hidden = !closed;
  note.textContent = closed ? text : '';
  for (const r of radios()) {
    if (r.value !== 'post') {
      r.disabled = closed;
      if (closed && r.checked) r.checked = false;
    }
  }
  syncShowButton();
}

function stopPoll() {
  clearTimeout(pollTimer);
  pollTimer = null;
}

function hideQr() {
  stopPoll();
  code = null;
  $('#qr-box').hidden = true;
  $('#cup-qr').removeAttribute('src');
}

function paint(status) {
  const s = STATES[status] || STATES.active;
  $('#qr-stage').dataset.state = status;
  const overlay = $('#qr-overlay');
  overlay.hidden = !s.overlay;
  overlay.dataset.kind = s.kind;
  $('#qr-overlay-text').textContent = s.overlay || '';
  $('#qr-overlay-icon').className = 'ti ' + s.icon;
  const badge = $('#qr-status');
  badge.dataset.kind = s.kind;
  badge.querySelector('i').className = 'ti ' + s.icon;
  badge.querySelector('span').textContent = s.badge;
  $('#qr-hint').hidden = status !== 'active';
}

/** Kod zeskanowany: wolontariusz ma wybrać kategorię od nowa, żeby dostać kolejny kod. */
function onConsumed() {
  clearSelection();
  refresh();
}

function schedulePoll() {
  stopPoll();
  if (!code || FINAL.has(code.status) || document.hidden) return;
  pollTimer = setTimeout(poll, POLL_MS);
}

async function poll() {
  const mine = code;
  if (!mine) return;
  try {
    const r = await api('GET', '/api/volunteer/cup-qr/' + encodeURIComponent(mine.id));
    if (code !== mine) return; // w międzyczasie wystawiono inny kod albo ukryto ten
    if (r.status !== mine.status) {
      const wasActive = mine.status === 'active';
      mine.status = r.status;
      if (r.status === 'scanned') mine.scannedAt = Date.now();
      paint(r.status);
      if (wasActive && r.status !== 'revoked') onConsumed();
      else if (FINAL.has(r.status)) refresh();
    }
    if (mine.status === 'scanned' && Date.now() - mine.scannedAt > POLL_MAX_MS) return;
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    if (e.status === 404) { hideQr(); return; }
  }
  schedulePoll();
}

/** Wystawia nowy jednorazowy kod dla wybranej kategorii (poprzedni niezeskanowany kod serwer unieważnia). */
async function showCode() {
  const category = selectedCategory();
  if (!category || !ctx.boothId) return;
  const btn = $('#qr-show');
  btn.disabled = true;
  try {
    const r = await api('POST', '/api/volunteer/cup-qr', ctx.role === 'admin' ? { category, booth_id: ctx.boothId } : { category });
    stopPoll();
    setMessage(msg, '');
    code = { id: r.id, status: 'active', scannedAt: 0 };
    $('#qr-cat-label').textContent = CATS[r.category] ? CATS[r.category].label : r.category;
    $('#qr-cat-icon').className = 'ti ' + (CATS[r.category] ? CATS[r.category].icon : 'ti-qrcode');
    $('#cup-qr').src = qrUrl(r.path);
    paint('active');
    $('#qr-box').hidden = false;
    $('#qr-box').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    schedulePoll();
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    setMessage(msg, e.detail || e.message, 'error');
  } finally {
    syncShowButton();
  }
}

function wire() {
  if (wired) return;
  wired = true;
  $('#qr-show').addEventListener('click', showCode);
  $('#qr-hide').addEventListener('click', hideQr);
  for (const r of radios()) r.addEventListener('change', syncShowButton);
  // Karta w tle nie odpytuje serwera; po powrocie sprawdzamy stan od razu.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopPoll();
    else if (code && !FINAL.has(code.status)) poll();
  });
}

/** Uruchamia (lub przelacza na inne stoisko) czesc wolontariusza. me = { role, booth: {id,name}|null }. */
export function initVolunteer(me) {
  wire();
  const boothId = me && me.booth ? me.booth.id : '';
  if (boothId !== ctx.boothId) { hideQr(); clearSelection(); }
  ctx = { role: me ? me.role : 'volunteer', boothId };
  if (!boothId) {
    clearTimeout(refreshTimer);
    return Promise.resolve();
  }
  return refresh();
}

export function stopVolunteer() {
  clearTimeout(refreshTimer);
  hideQr();
  ctx = { role: 'volunteer', boothId: '' };
}
