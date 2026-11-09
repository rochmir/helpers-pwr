// Czesc panelu dla wolontariusza (liczniki stoiska i dynamiczny kod QR do Pucharu). Logowanie i wybor stoiska robi login.js.
import { api, $, setMessage, qrUrl } from './common.js';

const msg = $('#panel-msg');
const CAT_LABEL = {
  nowy: 'Nowy dawca',
  zarejestrowany: 'Zarejestrowany dawca',
  faktyczny: 'Faktyczny dawca',
  post: 'Post / story (+5 prób)',
};
let refreshTimer = null;
let qrTimer = null; // następne pobranie kodu
let tickTimer = null; // odliczanie "Kod zmieni się za N s"
let qrVisible = false;
let qrExpiresAt = 0; // ms
let ctx = { role: 'volunteer', boothId: '' };
let wired = false;
let cupClosed = false;

const meUrl = () => '/api/volunteer/me' + (ctx.role === 'admin' && ctx.boothId ? '?booth_id=' + encodeURIComponent(ctx.boothId) : '');
const selectedCategory = () => {
  const r = document.querySelector('input[name="qr-cat"]:checked');
  return r ? r.value : 'nowy';
};

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
  for (const r of document.querySelectorAll('input[name="qr-cat"]')) {
    if (r.value !== 'post') r.disabled = closed;
  }
  if (closed && selectedCategory() !== 'post') {
    const post = document.querySelector('input[name="qr-cat"][value="post"]');
    if (post) post.checked = true;
    if (qrVisible) fetchQr();
  }
}

function stopQrTimers() {
  clearTimeout(qrTimer);
  clearInterval(tickTimer);
  qrTimer = null;
  tickTimer = null;
}

function hideQr() {
  qrVisible = false;
  stopQrTimers();
  $('#qr-box').hidden = true;
  $('#qr-hide').hidden = true;
  $('#qr-show').hidden = false;
  $('#cup-qr').removeAttribute('src');
}

function tick() {
  const left = Math.max(0, Math.ceil((qrExpiresAt - Date.now()) / 1000));
  $('#qr-left').textContent = 'Kod zmieni się za ' + left + ' s';
}

/** Pobiera świeży kod dla wybranej kategorii i planuje następne pobranie po ``valid_seconds``. */
async function fetchQr() {
  stopQrTimers();
  if (!qrVisible || !ctx.boothId) return;
  const category = selectedCategory();
  try {
    const q = '?category=' + encodeURIComponent(category) + (ctx.role === 'admin' ? '&booth_id=' + encodeURIComponent(ctx.boothId) : '');
    const r = await api('GET', '/api/volunteer/cup-qr' + q);
    if (!qrVisible || category !== selectedCategory()) return; // w międzyczasie zmieniono kategorię albo ukryto kod
    setMessage(msg, '');
    $('#qr-cat-label').textContent = CAT_LABEL[r.category] || r.category;
    $('#cup-qr').src = qrUrl(r.path);
    $('#qr-box').hidden = false;
    qrExpiresAt = Date.now() + r.valid_seconds * 1000;
    tick();
    tickTimer = setInterval(tick, 500);
    qrTimer = setTimeout(fetchQr, r.valid_seconds * 1000);
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    setMessage(msg, e.detail || e.message, 'error');
    if (e.status === 410) { $('#qr-box').hidden = true; return; } // termin Pucharu minął
    qrTimer = setTimeout(fetchQr, 5000);
  }
}

function wire() {
  if (wired) return;
  wired = true;
  $('#qr-show').addEventListener('click', () => {
    qrVisible = true;
    $('#qr-show').hidden = true;
    $('#qr-hide').hidden = false;
    fetchQr();
  });
  $('#qr-hide').addEventListener('click', hideQr);
  for (const r of document.querySelectorAll('input[name="qr-cat"]')) {
    r.addEventListener('change', () => { if (qrVisible) fetchQr(); });
  }
  // Ekran telefonu wraca z uśpienia: stary kod mógł już wygasnąć, więc odświeżamy od razu.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && qrVisible) fetchQr();
  });
}

/** Uruchamia (lub przelacza na inne stoisko) czesc wolontariusza. me = { role, booth: {id,name}|null }. */
export function initVolunteer(me) {
  wire();
  const boothId = me && me.booth ? me.booth.id : '';
  if (boothId !== ctx.boothId) hideQr();
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
