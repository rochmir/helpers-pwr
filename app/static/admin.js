import { api, $, h, icon, setMessage, formatWarsaw, formatDateTime, formatDateRange, renderGenotype, loadTurnstile, requireToken, getConfig, facultyLabel } from './common.js';
import { renderSocial, renderPlayerCert, renderDonorCert, showDownload } from './cert.js';

const msg = $('#admin-msg');
let ts = null;
let booths = [];
let faculties = [];
const STATUS_PL = { ACTIVE: 'aktywny', USED: 'użyty', EXPIRED: 'wygasły' };

async function guard(fn, target = msg) {
  setMessage(target, '');
  try { return await fn(); } catch (e) {
    if (e.status === 401 || e.status === 403) { await showLogin(); return undefined; }
    setMessage(target, e.detail || e.message, 'error');
    return undefined;
  }
}

async function showLogin() {
  $('#admin-panel').hidden = true;
  $('#login-section').hidden = false;
  if (!ts) { try { ts = await loadTurnstile($('#turnstile')); } catch (e) { setMessage(msg, e.message, 'error'); } }
}

async function showPanel() {
  $('#login-section').hidden = true;
  $('#admin-panel').hidden = false;
  await Promise.all([loadBooths(), loadVolunteers(), loadCodes(), loadDictionary(), loadDays(), refreshTestStatus(), loadHours(), loadRaffle()]);
}

async function loadHours() {
  await guard(async () => { $('#booth-hours').value = (await api('GET', '/api/admin/booth-hours')).hours; });
}

async function init() {
  try {
    await api('GET', '/api/admin/me');
    await showPanel();
  } catch (e) {
    if (e.status === 401 || e.status === 403) await showLogin();
    else setMessage(msg, e.detail, 'error');
  }
}

$('#login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  setMessage(msg, '');
  try {
    const cf = requireToken(ts);
    await api('POST', '/api/admin/login', { secret: $('#secret').value, cf_turnstile: cf ?? null });
    $('#secret').value = '';
    await showPanel();
  } catch (e) {
    setMessage(msg, e.status === 401 ? 'Błędny sekret administratora.' : (e.detail || e.message), 'error');
  } finally {
    if (ts) ts.reset();
  }
});

$('#logout-btn').addEventListener('click', async () => {
  try { await api('POST', '/api/admin/logout'); } catch (e) { /* ignoruj */ }
  await showLogin();
});

// ---------- stoiska ----------
async function loadBooths() {
  await guard(async () => {
    booths = await api('GET', '/api/admin/booths');
    const body = $('#booths-body');
    body.textContent = '';
    for (const b of booths) {
      const act = (a, ico, label) => h('button', { class: 'btn btn-small', type: 'button', 'data-action': a, 'data-id': b.id }, icon(ico), label);
      const genotypeCell = h('div', { class: 'genotype genotype-mini', 'aria-label': 'Genotyp stoiska' });
      renderGenotype(genotypeCell, b.current_genotype);
      body.append(h('tr', {},
        h('td', { class: 'mono' }, b.id), h('td', {}, b.name),
        h('td', {}, [b.building, formatDateRange(b.date_from, b.date_to)].filter(Boolean).join(', ')),
        h('td', {}, b.registered), h('td', {}, b.active_codes),
        h('td', {}, b.matches_count), h('td', {}, b.rolls_count),
        h('td', {}, genotypeCell),
        h('td', { class: 'actions' },
          h('a', { class: 'btn btn-small', href: '/stoisko/' + encodeURIComponent(b.id), target: '_blank', rel: 'noopener' }, icon('ti-device-tv'), 'Otwórz ekran stoiska'),
          act('playlink', 'ti-link', 'Link do gry (ważny ~2 min)'),
          act('rename', 'ti-pencil', 'Zmień nazwę'), act('details', 'ti-calendar', 'Budynek i termin'),
          act('reset', 'ti-refresh', 'Resetuj genotyp'), act('delete', 'ti-trash', 'Usuń'))));
    }
    const sel = $('#cf-booth');
    const cur = sel.value;
    sel.textContent = '';
    sel.append(h('option', { value: '' }, 'Wszystkie'));
    for (const b of booths) sel.append(h('option', { value: b.id }, b.name + ' (' + b.id + ')'));
    sel.value = cur;
    fillBoothSelects();
  });
}

$('#booths-body').addEventListener('click', async (ev) => {
  const btn = ev.target.closest('button[data-action]');
  if (!btn) return;
  const id = btn.dataset.id;
  const b = booths.find((x) => x.id === id);
  const enc = encodeURIComponent(id);
  await guard(async () => {
    switch (btn.dataset.action) {
      case 'rename': {
        const name = prompt('Nowa nazwa stoiska:', b ? b.name : '');
        if (!name || !name.trim()) return;
        await api('PATCH', '/api/admin/booths/' + enc, { name: name.trim() });
        break;
      }
      case 'details': {
        const building = prompt('Budynek (np. C-13):', b ? b.building : '');
        if (building === null) return;
        const from = prompt('Stanowisko od (RRRR-MM-DD, puste = bez daty):', b && b.date_from ? b.date_from : '');
        if (from === null) return;
        const to = prompt('Stanowisko do (RRRR-MM-DD, puste = bez daty):', b && b.date_to ? b.date_to : '');
        if (to === null) return;
        await api('PATCH', '/api/admin/booths/' + enc, { building: building.trim(), date_from: from.trim(), date_to: to.trim() });
        break;
      }
      case 'playlink':
        await showPlayLink(id, $('#booth-link-out'));
        return;
      case 'reset':
        if (!confirm('Zresetować genotyp stoiska „' + id + '”?')) return;
        await api('POST', '/api/admin/booths/' + enc + '/reset-genotype');
        break;
      case 'delete':
        if (!confirm('Usunąć stoisko „' + id + '”? Tej operacji nie można cofnąć.')) return;
        await api('DELETE', '/api/admin/booths/' + enc);
        break;
    }
    await loadBooths();
  });
});

$('#booth-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await guard(async () => {
    await api('POST', '/api/admin/booths', { id: $('#nb-id').value.trim(), name: $('#nb-name').value.trim(),
      building: $('#nb-building').value.trim(), date_from: $('#nb-from').value || null, date_to: $('#nb-to').value || null });
    ev.target.reset();
    setMessage(msg, 'Stoisko utworzone.', 'ok');
    await loadBooths();
  });
});

$('#hours-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await guard(async () => {
    const r = await api('PUT', '/api/admin/booth-hours', { hours: $('#booth-hours').value });
    $('#booth-hours').value = r.hours;
    setMessage(msg, 'Godziny stanowisk zapisane.', 'ok');
  });
});

/** Pokazuje aktualny link do gry stoiska (token QR; admin dostaje go ze stanu stoiska). */
async function showPlayLink(boothId, el) {
  const st = await api('GET', '/api/booth/' + encodeURIComponent(boothId) + '/state');
  if (!st.play_path) throw new Error('Nie udało się pobrać linku do gry.');
  el.hidden = false;
  el.className = 'inline-result msg msg-info';
  el.textContent = '';
  el.append(h('p', {}, 'Link do gry dla stoiska „' + boothId + '” (ważny ok. 2 minut od teraz; przepustka po wejściu trwa 30 minut):'),
    h('a', { href: st.play_path, target: '_blank', rel: 'noopener' }, location.origin + st.play_path));
}

// ---------- konta wolontariuszy ----------
async function loadVolunteers() {
  await guard(async () => {
    const list = await api('GET', '/api/admin/volunteers');
    const body = $('#vol-body');
    body.textContent = '';
    $('#vol-empty').hidden = list.length > 0;
    for (const v of list) {
      body.append(h('tr', {},
        h('td', { class: 'mono' }, v.login), h('td', {}, formatDateTime(v.created_at)),
        h('td', { class: 'actions' },
          h('button', { class: 'btn btn-small', type: 'button', 'data-vol': 'reset', 'data-login': v.login }, icon('ti-key'), 'Nowe hasło'),
          h('button', { class: 'btn btn-small', type: 'button', 'data-vol': 'delete', 'data-login': v.login }, icon('ti-trash'), 'Usuń'))));
    }
  });
}

async function showCredentials(login, password) {
  const cfg = await getConfig();
  const base = ((cfg && cfg.public_url) || location.origin).replace(/\/+$/, '');
  $('#vol-message').value = "Cześć! Masz konto wolontariusza w akcji Helpers' Generation na PWr.\n"
    + 'Panel: ' + base + '/wolontariusz?login=' + encodeURIComponent(login) + '\n'
    + 'Login: ' + login + '\n'
    + 'Hasło: ' + password + '\n'
    + 'Po zalogowaniu wybierz swoje stoisko.';
  $('#vol-copy-status').textContent = '';
  $('#vol-out').hidden = false;
  $('#vol-message').scrollIntoView({ block: 'nearest' });
}

$('#vol-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await guard(async () => {
    const body = { login: $('#vol-login').value.trim().toLowerCase() };
    if ($('#vol-password').value) body.password = $('#vol-password').value;
    const r = await api('POST', '/api/admin/volunteers', body);
    ev.target.reset();
    await showCredentials(r.login, r.password);
    setMessage(msg, 'Konto utworzone.', 'ok');
    await loadVolunteers();
  });
});

$('#vol-body').addEventListener('click', async (ev) => {
  const btn = ev.target.closest('button[data-vol]');
  if (!btn) return;
  const login = btn.dataset.login;
  await guard(async () => {
    if (btn.dataset.vol === 'reset') {
      if (!confirm('Ustawić nowe hasło dla „' + login + '”? Wolontariusz zostanie wylogowany.')) return;
      const r = await api('POST', '/api/admin/volunteers/' + encodeURIComponent(login) + '/reset-password', {});
      await showCredentials(r.login, r.password);
      setMessage(msg, 'Nowe hasło ustawione.', 'ok');
    } else {
      if (!confirm('Usunąć konto „' + login + '”? Wolontariusz zostanie wylogowany.')) return;
      await api('DELETE', '/api/admin/volunteers/' + encodeURIComponent(login));
      $('#vol-out').hidden = true;
      setMessage(msg, 'Konto usunięte.', 'ok');
    }
    await loadVolunteers();
  });
});

$('#vol-copy').addEventListener('click', async () => {
  const ta = $('#vol-message');
  const status = $('#vol-copy-status');
  try {
    await navigator.clipboard.writeText(ta.value);
    status.textContent = 'Skopiowano.';
  } catch (e) {
    ta.focus();
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    status.textContent = ok ? 'Skopiowano.' : 'Zaznaczono tekst, skopiuj go ręcznie (Ctrl+C).';
  }
});

// ---------- kody ----------
async function loadCodes() {
  await guard(async () => {
    const qs = new URLSearchParams();
    if ($('#cf-booth').value) qs.set('booth_id', $('#cf-booth').value);
    if ($('#cf-status').value) qs.set('status', $('#cf-status').value);
    const codes = await api('GET', '/api/admin/codes?' + qs);
    const body = $('#codes-body');
    body.textContent = '';
    for (const c of codes) {
      body.append(h('tr', { class: 'code-' + c.status.toLowerCase() },
        h('td', { class: 'mono' }, c.code), h('td', {}, c.booth_id || ''),
        h('td', {}, h('span', { class: 'status-tag tag-' + c.status.toLowerCase() }, STATUS_PL[c.status] || c.status)), h('td', {}, formatDateTime(c.created_at)),
        h('td', {}, c.status === 'ACTIVE'
          ? h('button', { class: 'btn btn-small', type: 'button', 'data-cancel': c.code }, icon('ti-x'), 'Anuluj') : '')));
    }
    if (!codes.length) body.append(h('tr', {}, h('td', { colspan: 5 }, 'Brak kodów.')));
  });
}

$('#codes-filter').addEventListener('submit', (ev) => { ev.preventDefault(); loadCodes(); });
$('#codes-body').addEventListener('click', async (ev) => {
  const cancelBtn = ev.target.closest && ev.target.closest('[data-cancel]');
  if (!cancelBtn) return;
  const code = cancelBtn.getAttribute('data-cancel');
  await guard(async () => {
    await api('POST', '/api/admin/codes/' + encodeURIComponent(code) + '/cancel');
    await loadCodes();
  });
});

// ---------- słownik ----------
async function loadDictionary() {
  await guard(async () => {
    const d = await api('GET', '/api/admin/dictionary');
    $('#dictionary').value = JSON.stringify(d, null, 2);
    const sel = $('#pv-donor-faculty');
    sel.textContent = '';
    faculties = d.faculties || [];
    for (const f of faculties) sel.append(h('option', { value: f.code }, facultyLabel(f)));
  });
}

$('#dict-save').addEventListener('click', async () => {
  const out = $('#dict-msg');
  let parsed;
  try { parsed = JSON.parse($('#dictionary').value); } catch (e) {
    setMessage(out, 'Niepoprawny JSON: ' + e.message, 'error');
    return;
  }
  await guard(async () => {
    await api('PUT', '/api/admin/dictionary', parsed);
    setMessage(out, 'Zapisano słownik.', 'ok');
  }, out);
});

// ---------- grafika social ----------
async function loadDays() {
  await guard(async () => {
    const days = await api('GET', '/api/admin/days');
    const sel = $('#social-date');
    sel.textContent = '';
    sel.append(h('option', { value: 'all' }, 'Cała akcja'));
    for (const d of days) {
      const v = typeof d === 'string' ? d : d.date;
      sel.append(h('option', { value: v }, v));
    }
  });
}

$('#social-btn').addEventListener('click', async () => {
  await guard(async () => {
    const summary = await api('GET', '/api/admin/summary?date=' + encodeURIComponent($('#social-date').value));
    const fmt = $('#social-format').value;
    const canvas = await renderSocial(summary, fmt);
    const tag = summary.scope === 'day' ? summary.date : 'cala-akcja';
    showDownload(canvas, $('#social-output'), 'podsumowanie-' + tag + '-' + fmt.replace(':', 'x') + '.png');
  });
});


// ---------- losowanie finalowe ----------
const raffleMsg = $('#raffle-msg');
let raffleBooths = {};

function genotypeCell(g) {
  const el = h('div', { class: 'genotype genotype-mini', 'aria-label': 'Genotyp' });
  renderGenotype(el, g);
  return el;
}

function boothLabel(id) { return raffleBooths[id] || id; }

async function loadRaffle() {
  await guard(async () => {
    const r = await api('GET', '/api/admin/raffle');
    raffleBooths = Object.fromEntries(r.entries.map((e) => [e.booth_id, e.booth_name || e.booth_id]));
    const left = r.entries_count - r.draws.length;
    $('#raffle-count').textContent = 'Trafień 10/10 w losowaniu: ' + r.entries_count
      + (r.draws.length ? ' (wylosowano: ' + r.draws.length + ', do wylosowania: ' + Math.max(0, left) + ')' : '');
    $('#raffle-draw').disabled = left <= 0;
    const draws = $('#raffle-draws-body');
    draws.textContent = '';
    for (const d of r.draws) {
      draws.append(h('tr', {}, h('td', {}, formatWarsaw(d.drawn_at)), h('td', {}, genotypeCell(d.genotype)),
        h('td', {}, formatWarsaw(d.matched_at)), h('td', {}, boothLabel(d.booth_id))));
    }
    $('#raffle-draws').hidden = r.draws.length === 0;
    const body = $('#raffle-entries-body');
    body.textContent = '';
    for (const e of r.entries) {
      body.append(h('tr', {}, h('td', {}, formatWarsaw(e.matched_at)), h('td', {}, genotypeCell(e.genotype)),
        h('td', {}, e.booth_name || e.booth_id)));
    }
  }, raffleMsg);
}

$('#raffle-refresh').addEventListener('click', loadRaffle);
$('#raffle-draw').addEventListener('click', async () => {
  if (!confirm('Wylosować genotyp spośród wszystkich trafień 10/10? Wynik zostanie zapisany i nie można go cofnąć.')) return;
  await guard(async () => {
    const d = await api('POST', '/api/admin/raffle/draw');
    const box = $('#raffle-pick');
    box.hidden = false;
    box.textContent = '';
    box.append(
      h('h3', {}, 'Wylosowany genotyp'),
      h('div', { class: 'genotype', 'aria-label': 'Wylosowany genotyp' }),
      h('p', {}, 'Trafiony: ' + formatWarsaw(d.matched_at) + ', stoisko: ' + (d.booth_name || d.booth_id)
        + '. Losowanie: ' + formatWarsaw(d.drawn_at) + '. Zostało do wylosowania: ' + d.remaining + '.'),
    );
    renderGenotype(box.querySelector('.genotype'), d.genotype);
    await loadRaffle();
  }, raffleMsg);
});

// ---------- podglad grafik (tylko lokalnie, bez zapisu na serwerze) ----------
$('#pv-player-btn').addEventListener('click', async () => {
  const canvas = await renderPlayerCert($('#pv-player-nick').value, '0123012301', new Date().toISOString());
  showDownload(canvas, $('#pv-player-out'), 'podglad-certyfikat-gracza.png');
});

$('#pv-donor-btn').addEventListener('click', async () => {
  const sel = $('#pv-donor-faculty');
  const fac = faculties.find((f) => f.code === sel.value);
  const facultyName = fac && fac.code !== 'INNE' ? fac.name : '';
  const canvas = await renderDonorCert({ name: $('#pv-donor-name').value, facultyName });
  showDownload(canvas, $('#pv-donor-out'), 'podglad-certyfikat-dawcy.png');
});

// ---------- testy ----------
const T = '/api/admin/test/';

function fillBoothSelects() {
  for (const [id, withEmpty] of [['#t-booth', false], ['#t-fake-booth', true]]) {
    const sel = $(id);
    const cur = sel.value;
    sel.textContent = '';
    if (withEmpty) sel.append(h('option', { value: '' }, 'losowe'));
    for (const b of booths) sel.append(h('option', { value: b.id }, b.name + ' (' + b.id + ')'));
    if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
  }
  updateTestLinks();
}

function updateTestLinks() {
  const id = $('#t-booth').value;
  $('#t-watch-link').href = id ? '/stoisko/' + encodeURIComponent(id) : '/';
}
$('#t-booth').addEventListener('change', updateTestLinks);
$('#t-play-link').addEventListener('click', () => runTest($('#t-arm-result'), async () => {
  const id = $('#t-booth').value;
  if (!id) throw new Error('Wybierz stoisko.');
  await showPlayLink(id, $('#t-arm-result'));
}));

/** Wynik/blad pod przyciskiem testowym. */
function testResult(el, text, kind) {
  el.hidden = !text;
  el.textContent = text || '';
  el.className = 'inline-result msg msg-' + kind;
}

async function runTest(el, fn) {
  try { await fn(); } catch (e) {
    if (e.status === 401 || e.status === 403) { await showLogin(); return; }
    testResult(el, e.detail || e.message, 'error');
  }
}

async function refreshTestStatus() {
  const el = $('#t-status');
  try {
    const st = await api('GET', T + 'status');
    el.textContent = (st.game_session ? 'Sesja gry: jest' : 'Sesja gry: brak (otwórz link do gry w tej przeglądarce)')
      + ' · Uzbrojone 10/10: ' + (st.armed ? 'tak' : 'nie')
      + ' · Pozostałe próby: ' + (st.attempts_left === null ? '-' : st.attempts_left);
  } catch (e) {
    if (e.status === 401 || e.status === 403) { await showLogin(); return; }
    el.textContent = 'Błąd: ' + (e.detail || e.message);
  }
}
$('#t-refresh').addEventListener('click', refreshTestStatus);

$('#t-arm').addEventListener('click', () => runTest($('#t-arm-result'), async () => {
  await api('POST', T + 'arm-win');
  testResult($('#t-arm-result'), 'Uzbrojone: następne losowanie w tej przeglądarce da 10/10. Otwórz grę przez „Link do gry”, wybierz stoisko i kliknij „Losuj”.', 'ok');
  await refreshTestStatus();
}));

$('#t-reset').addEventListener('click', () => runTest($('#t-arm-result'), async () => {
  const r = await api('POST', T + 'reset-my-game');
  testResult($('#t-arm-result'), 'Próby zresetowane. Pozostałe próby dziś: ' + r.attempts_left + '.', 'ok');
  await refreshTestStatus();
}));

$('#t-force').addEventListener('click', () => runTest($('#t-force-result'), async () => {
  const id = $('#t-booth').value;
  if (!id) throw new Error('Wybierz stoisko.');
  const r = await api('POST', T + 'force-win', { booth_id: id });
  const box = $('#t-force-result');
  box.hidden = false;
  box.className = 'inline-result msg msg-ok';
  box.textContent = '';
  const oldG = h('div', { class: 'genotype genotype-mini' });
  const newG = h('div', { class: 'genotype genotype-mini' });
  renderGenotype(oldG, r.old_genotype);
  renderGenotype(newG, r.new_genotype);
  box.append(h('p', {}, 'Trafienie wymuszone na stoisku „' + id + '”.'),
    h('p', {}, 'Stary genotyp: ', oldG), h('p', {}, 'Nowy genotyp: ', newG),
    h('a', { href: '/stoisko/' + encodeURIComponent(id), target: '_blank', rel: 'noopener' }, 'Zobacz ekran stoiska'));
  await loadBooths();
}));

$('#t-fake').addEventListener('click', () => runTest($('#t-fake-result'), async () => {
  const body = { count: Number($('#t-fake-count').value) };
  if ($('#t-fake-booth').value) body.booth_id = $('#t-fake-booth').value;
  if ($('#t-fake-date').value) body.date = $('#t-fake-date').value;
  const r = await api('POST', T + 'fake-registrations', body);
  testResult($('#t-fake-result'), 'Dodano testowych rejestracji: ' + r.created + '.', 'ok');
  await loadBooths();
}));

$('#t-wipe-confirm').addEventListener('input', () => {
  $('#t-wipe').disabled = $('#t-wipe-confirm').value.trim() !== 'USUŃ';
});

$('#t-wipe').addEventListener('click', () => runTest($('#t-wipe-result'), async () => {
  if (!confirm('Na pewno usunąć wszystkie rejestracje, kody i dane graczy? Tej operacji nie można cofnąć.')) return;
  await api('POST', T + 'wipe', { confirm: $('#t-wipe-confirm').value.trim() });
  $('#t-wipe-confirm').value = '';
  $('#t-wipe').disabled = true;
  testResult($('#t-wipe-result'), 'Dane testowe wyczyszczone. Stoiska dostały nowe genotypy.', 'ok');
  await Promise.all([loadBooths(), loadCodes(), loadDays(), refreshTestStatus()]);
}));

init();
