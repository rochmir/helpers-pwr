// Jedno logowanie dla wolontariuszy i administratorow. Po zalogowaniu ta sama strona pokazuje funkcje wg rangi.
import { api, $, h, setMessage } from './common.js';
import { initVolunteer, stopVolunteer } from './wolontariusz.js';
import { initAdmin } from './admin.js';

const msg = $('#panel-msg');
const ROLE_PL = { admin: 'administrator', volunteer: 'wolontariusz' };
let adminLoaded = false;
let boothsLoaded = false;
let navWired = false;
const SECTION_KEY = 'hp_admin_section'; // zapamietana sekcja panelu admina (tylko w tej przegladarce)

function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* tryb prywatny */ } }

/** Lista rozwijana sekcji admina: widoczna jest jedna, reszta ma atrybut hidden (DOM i pola formularzy zostaja). */
const BOOTH_SECTION = 'stoisko';

function wireAdminNav() {
  if (navWired) return;
  navWired = true;
  const sel = $('#admin-section');
  const sections = [...document.querySelectorAll('#admin-part > section.card')];
  const slug = (sec) => sec.id.replace(/-section$/, '');
  const panel = $('#panel');
  sel.append(h('option', { value: BOOTH_SECTION }, 'Stoisko i tokeny'));
  for (const sec of sections) {
    sel.append(h('option', { value: slug(sec) }, sec.querySelector('h2').textContent.trim()));
  }
  const known = (v) => v === BOOTH_SECTION || sections.some((sec) => slug(sec) === v);
  const apply = (v, store) => {
    if (!known(v)) v = BOOTH_SECTION;
    sel.value = v;
    panel.classList.toggle('admin-view-booth', v === BOOTH_SECTION);
    panel.classList.toggle('admin-view-section', v !== BOOTH_SECTION);
    for (const sec of sections) sec.hidden = slug(sec) !== v;
    if (store) {
      lsSet(SECTION_KEY, v);
      try { history.replaceState(null, '', '#' + v); } catch (e) { /* bez hasha */ }
    }
  };
  const fromHash = () => location.hash.replace(/^#/, '').replace(/-section$/, '');
  apply(fromHash() || lsGet(SECTION_KEY) || '', false);
  sel.addEventListener('change', () => apply(sel.value, true));
  window.addEventListener('hashchange', () => apply(fromHash(), true));
}

async function showLogin() {
  stopVolunteer();
  $('#panel').hidden = true;
  $('#login-section').hidden = false;
  const prefill = new URLSearchParams(location.search).get('login');
  if (prefill && !$('#login').value) {
    $('#login').value = prefill.trim().toLowerCase();
    $('#password').focus();
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
  $('#admin-switch').hidden = me.role !== 'admin';
  if (me.role !== 'admin') $('#panel').classList.remove('admin-view-booth', 'admin-view-section');
  if (me.role === 'admin') wireAdminNav();
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
    await api('POST', '/api/auth/login', {
      login: $('#login').value.trim().toLowerCase(),
      password: $('#password').value,
    });
    $('#password').value = '';
    await showPanel(await api('GET', '/api/auth/me'));
  } catch (e) {
    setMessage(msg, e.status === 401 ? 'Błędny login lub hasło.' : (e.detail || e.message), 'error');
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
