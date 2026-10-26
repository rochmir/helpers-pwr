import { api, $, h, icon, setMessage, formatTime, formatDateTime, qrUrl, loadTurnstile, requireToken } from './common.js';

const prefillLogin = new URLSearchParams(location.search).get('login');

const msg = $('#vol-msg');
let ts = null;
let isAdmin = false;
let refreshTimer = null;
const STATUS_PL = { ACTIVE: 'aktywny', USED: 'użyty', EXPIRED: 'wygasły' };

function show(id, on) { $('#' + id).hidden = !on; }

async function loadBoothChoices() {
  const sel = $('#booth-id');
  if (sel.options.length > 1) return;
  try {
    for (const b of await api('GET', '/api/booths')) sel.append(h('option', { value: b.id }, b.name));
  } catch (e) {
    setMessage(msg, 'Nie udało się pobrać listy stoisk: ' + (e.detail || e.message), 'error');
  }
}

async function showLogin() {
  clearTimeout(refreshTimer);
  show('panel-section', false);
  show('login-section', true);
  if (prefillLogin && !$('#login').value) {
    $('#login').value = prefillLogin.trim().toLowerCase();
    $('#password').focus();
  }
  loadBoothChoices();
  if (!ts) {
    try { ts = await loadTurnstile($('#turnstile')); } catch (e) { setMessage(msg, e.message, 'error'); }
  }
}

function renderCodes(codes) {
  const body = $('#codes-body');
  body.textContent = '';
  $('#codes-empty').hidden = codes.length > 0;
  for (const c of codes) {
    const cancel = c.status === 'ACTIVE'
      ? h('button', { class: 'btn btn-small', type: 'button', 'data-cancel': c.code }, icon('ti-x'), 'Anuluj')
      : '';
    body.append(h('tr', { class: 'code-' + c.status.toLowerCase() },
      h('td', { class: 'mono' }, c.code),
      h('td', {}, c.kind === 'actual' ? 'faktyczny' : 'potencjalny'),
      h('td', {}, h('span', { class: 'status-tag tag-' + c.status.toLowerCase() }, STATUS_PL[c.status] || c.status)),
      h('td', {}, formatDateTime(c.created_at)),
      h('td', {}, formatTime(c.expires_at)),
      h('td', {}, cancel)));
  }
}

async function loadAdminBooths(current) {
  const sel = $('#admin-booth');
  if (sel.options.length) return;
  const booths = await api('GET', '/api/admin/booths');
  for (const b of booths) sel.append(h('option', { value: b.id }, b.name + ' (' + b.id + ')'));
  if (current) sel.value = current;
}

const meUrl = (boothId) => '/api/volunteer/me' + (boothId ? '?booth_id=' + encodeURIComponent(boothId) : '');

async function refresh() {
  clearTimeout(refreshTimer);
  try {
    const sel = $('#admin-booth');
    let me = await api('GET', meUrl(isAdmin ? sel.value : ''));
    isAdmin = me.role === 'admin';
    if (isAdmin) {
      await loadAdminBooths(me.booth && me.booth.id);
      // Admin bez wybranego stoiska: od razu pokaz pierwsze z listy.
      if (!me.booth && sel.value) me = await api('GET', meUrl(sel.value));
    }
    show('login-section', false);
    show('panel-section', true);
    $('#vol-booth-name').textContent = me.booth ? me.booth.name : 'Administrator';
    $('#booth-screen-link').href = me.booth ? '/stoisko/' + encodeURIComponent(me.booth.id) : '/';
    $('#c-potential').textContent = me.registered_potential ?? 0;
    $('#c-actual').textContent = me.registered_actual ?? 0;
    $('#c-matches').textContent = me.matches_count ?? 0;
    $('#c-rolls').textContent = me.rolls_count ?? 0;
    $('#admin-booth-pick').hidden = !isAdmin;
    renderCodes(me.codes || []);
    refreshTimer = setTimeout(refresh, 15000);
  } catch (e) {
    if (e.status === 401 || e.status === 403) await showLogin();
    else {
      setMessage(msg, e.detail, 'error');
      refreshTimer = setTimeout(refresh, 15000);
    }
  }
}

$('#login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  setMessage(msg, '');
  try {
    const cf = requireToken(ts);
    await api('POST', '/api/volunteer/auth', {
      login: $('#login').value.trim().toLowerCase(),
      password: $('#password').value,
      booth_id: $('#booth-id').value,
      cf_turnstile: cf ?? null,
    });
    $('#password').value = '';
    await refresh();
  } catch (e) {
    setMessage(msg, e.status === 401 ? 'Błędny login lub hasło.' : (e.detail || e.message), 'error');
  } finally {
    if (ts) ts.reset();
  }
});

$('#gen-btn').addEventListener('click', async () => {
  const btn = $('#gen-btn');
  btn.disabled = true;
  setMessage(msg, '');
  try {
    const body = isAdmin ? { booth_id: $('#admin-booth').value } : {};
    body.kind = $('#code-kind').value;
    if (body.kind === 'actual') {
      body.card_number = $('#card-number').value;
      body.card_date = $('#card-date').value;
      if (!body.card_number.trim() || !body.card_date) throw Object.assign(new Error('Podaj numer legitymacji i datę jej wydania.'), { detail: 'Podaj numer legitymacji i datę jej wydania.' });
    }
    const r = await api('POST', '/api/volunteer/generate-code', body);
    $('#code-big').textContent = r.code;
    $('#code-qr').src = qrUrl(r.confirm_path);
    $('#code-expires').textContent = formatTime(r.expires_at);
    $('#code-kind-label').textContent = r.kind === 'actual' ? 'Kod dawcy faktycznego' : 'Kod rejestracyjny';
    if (r.kind === 'actual') { $('#card-number').value = ''; $('#card-date').value = ''; }
    show('code-box', true);
    await refresh();
  } catch (e) {
    setMessage(msg, e.detail, 'error');
  } finally {
    btn.disabled = false;
  }
});

$('#codes-body').addEventListener('click', async (ev) => {
  const btn = ev.target.closest && ev.target.closest('[data-cancel]');
  if (!btn) return;
  try {
    await api('POST', '/api/volunteer/codes/' + encodeURIComponent(btn.getAttribute('data-cancel')) + '/cancel');
    await refresh();
  } catch (e) {
    setMessage(msg, e.detail, 'error');
  }
});

$('#logout-btn').addEventListener('click', async () => {
  try { await api('POST', '/api/volunteer/logout'); } catch (e) { /* ignoruj */ }
  show('code-box', false);
  isAdmin = false;
  $('#admin-booth').textContent = '';
  await showLogin();
});

$('#code-kind').addEventListener('change', () => { $('#actual-fields').hidden = $('#code-kind').value !== 'actual'; });

$('#admin-booth').addEventListener('change', () => { show('code-box', false); refresh(); });

refresh();
