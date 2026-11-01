// Jedno logowanie dla wolontariuszy i administratorow. Po zalogowaniu ta sama strona pokazuje funkcje wg rangi.
import { api, $, h, setMessage, loadTurnstile, requireToken } from './common.js';
import { initVolunteer, stopVolunteer } from './wolontariusz.js';
import { initAdmin } from './admin.js';

const msg = $('#panel-msg');
const ROLE_PL = { admin: 'administrator', volunteer: 'wolontariusz' };
let ts = null;
let adminLoaded = false;
let boothsLoaded = false;

async function showLogin() {
  stopVolunteer();
  $('#panel').hidden = true;
  $('#login-section').hidden = false;
  const prefill = new URLSearchParams(location.search).get('login');
  if (prefill && !$('#login').value) {
    $('#login').value = prefill.trim().toLowerCase();
    $('#password').focus();
  }
  if (!ts) {
    try { ts = await loadTurnstile($('#turnstile')); } catch (e) { setMessage(msg, e.message, 'error'); }
  }
}

async function loadBoothChoices() {
  if (boothsLoaded) return;
  const sel = $('#booth-pick');
  try {
    for (const b of await api('GET', '/api/booths')) sel.append(h('option', { value: b.id }, b.name));
    boothsLoaded = true;
  } catch (e) {
    setMessage(msg, 'Nie udało się pobrać listy stoisk: ' + (e.detail || e.message), 'error');
  }
}

async function showPanel(me) {
  $('#login-section').hidden = true;
  $('#panel').hidden = false;
  $('#who-login').textContent = me.login;
  $('#who-role').textContent = ROLE_PL[me.role] || me.role;
  $('#login-title').textContent = me.role === 'admin' ? 'Panel administratora' : 'Panel wolontariusza';
  $('#login-lead').textContent = me.role === 'admin'
    ? 'Stoiska, konta, liczby studentów, weryfikacja Tokenu Losu, regulaminy i dokumenty, partnerzy, ustawienia, grafiki i narzędzia testowe, a także generowanie tokenów rejestracyjnych.'
    : 'Wybierz stoisko i wygeneruj token rejestracyjny dla osoby po weryfikacji na stoisku.';
  await loadBoothChoices();
  const booth = me.booth && me.booth.id ? me.booth : null;
  $('#booth-pick').value = booth ? booth.id : '';
  $('#booth-hint').textContent = booth
    ? 'Tokeny i liczniki dotyczą wybranego stoiska. Możesz je zmienić w dowolnej chwili.'
    : 'Wybierz stoisko, przy którym dziś pracujesz. Dopiero wtedy pojawią się tokeny i liczniki.';
  $('#volunteer-part').hidden = !booth;
  await initVolunteer({ role: me.role, booth });
  $('#admin-part').hidden = me.role !== 'admin';
  if (me.role === 'admin' && !adminLoaded) {
    adminLoaded = true;
    await initAdmin();
  }
}

async function init() {
  try {
    await showPanel(await api('GET', '/api/auth/me'));
  } catch (e) {
    if (e.status === 401) await showLogin();
    else setMessage(msg, e.detail || e.message, 'error');
  }
}

$('#login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  setMessage(msg, '');
  try {
    const cf = requireToken(ts);
    await api('POST', '/api/auth/login', {
      login: $('#login').value.trim().toLowerCase(),
      password: $('#password').value,
      cf_turnstile: cf ?? null,
    });
    $('#password').value = '';
    await showPanel(await api('GET', '/api/auth/me'));
  } catch (e) {
    setMessage(msg, e.status === 401 ? 'Błędny login lub hasło.' : (e.detail || e.message), 'error');
  } finally {
    if (ts) ts.reset();
  }
});

$('#booth-pick').addEventListener('change', async () => {
  setMessage(msg, '');
  const id = $('#booth-pick').value;
  if (!id) return;
  try {
    await api('POST', '/api/auth/booth', { booth_id: id });
    await showPanel(await api('GET', '/api/auth/me'));
  } catch (e) {
    setMessage(msg, e.detail || e.message, 'error');
  }
});

$('#logout-btn').addEventListener('click', async () => {
  try { await api('POST', '/api/auth/logout'); } catch (e) { /* ignoruj */ }
  // Przeladowanie czysci stan sekcji admina (nastepny uzytkownik moze miec inna range).
  location.reload();
});

init();
