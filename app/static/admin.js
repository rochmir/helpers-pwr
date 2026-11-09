// Czesc panelu dla administratora. Logowanie i wybor rangi robi login.js, tu tylko sekcje admina.
import { api, $, h, icon, setMessage, formatWarsaw, formatDateTime, formatDateRange, renderGenotype, getConfig, facultyLabel } from './common.js';
import { renderSocial, renderPlayerCert, renderDonorCert, renderResultCert, showDownload, makeGraphic } from './cert.js';

const msg = $('#panel-msg');
let booths = [];
let faculties = [];

async function guard(fn, target = msg) {
  setMessage(target, '');
  try { return await fn(); } catch (e) {
    if (e.status === 401) { location.reload(); return undefined; }
    setMessage(target, e.detail || e.message, 'error');
    return undefined;
  }
}

/** Wczytuje wszystkie sekcje admina (wywolywane raz po zalogowaniu administratora). */
export async function initAdmin() {
  await Promise.all([loadBooths(), loadVolunteers(), loadDictionary(), loadDays(), refreshTestStatus(),
    loadHours(), loadWins(), loadPartners(), loadSettings(), loadLegal()]);
}

async function loadHours() {
  await guard(async () => { $('#booth-hours').value = (await api('GET', '/api/admin/booth-hours')).hours; });
}

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
        h('td', { class: 'mono' }, b.id), h('td', {}, b.is_lecture ? b.name + ' (bez wolontariusza, poza wykazami)' : b.name),
        h('td', {}, [b.building, formatDateRange(b.date_from, b.date_to)].filter(Boolean).join(', ')),
        h('td', {}, b.registered),
        h('td', {}, b.matches_count), h('td', {}, b.rolls_count),
        h('td', {}, genotypeCell),
        h('td', { class: 'actions' },
          h('a', { class: 'btn btn-small', href: '/stoisko/' + encodeURIComponent(b.id), target: '_blank', rel: 'noopener' }, icon('ti-device-tv'), 'Otwórz ekran stoiska'),
          act('playlink', 'ti-link', 'Link do symulatora (ważny ~2 min)'),
          act('rename', 'ti-pencil', 'Zmień nazwę'), act('details', 'ti-calendar', 'Budynek i termin'),
          act('reset', 'ti-refresh', 'Resetuj genotyp'), ...(b.is_lecture ? [] : [act('delete', 'ti-trash', 'Usuń')]))));
    }
    fillBoothSelects();
    await loadLectureLink();
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

/** Pole z pełnym linkiem do ekranu Zajęć (widoczne, gdy istnieje stanowisko is_lecture). */
async function loadLectureLink() {
  const box = $('#lecture-box');
  box.hidden = !booths.some((b) => b.is_lecture);
  if (box.hidden) return;
  $('#lecture-url').value = (await api('GET', '/api/admin/lecture-screen')).url;
}

$('#lecture-copy').addEventListener('click', async () => {
  const input = $('#lecture-url');
  const status = $('#lecture-status');
  try {
    await navigator.clipboard.writeText(input.value);
    status.textContent = 'Skopiowano.';
  } catch (e) {
    input.focus();
    input.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    status.textContent = ok ? 'Skopiowano.' : 'Zaznaczono link, skopiuj go ręcznie (Ctrl+C).';
  }
});

$('#lecture-rotate').addEventListener('click', async () => {
  if (!confirm('Wygenerować nowy link? Poprzedni przestanie działać, a ekrany otwarte ze starym linkiem stracą kod QR.')) return;
  await guard(async () => {
    $('#lecture-url').value = (await api('POST', '/api/admin/lecture-screen/rotate')).url;
    $('#lecture-status').textContent = 'Nowy link gotowy. Poprzedni nie działa.';
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

/** Pokazuje aktualny link do symulatora stoiska (token QR; admin dostaje go ze stanu stoiska). */
async function showPlayLink(boothId, el) {
  const st = await api('GET', '/api/booth/' + encodeURIComponent(boothId) + '/state');
  if (!st.play_path) throw new Error('Nie udało się pobrać linku do symulatora.');
  el.hidden = false;
  el.className = 'inline-result msg msg-info';
  el.textContent = '';
  el.append(h('p', {}, 'Link do symulatora dla stoiska „' + boothId + '” (ważny ok. 2 minut od teraz; przepustka po wejściu trwa 30 minut):'),
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
      const roleSel = h('select', { 'data-role-login': v.login, 'aria-label': 'Ranga konta ' + v.login },
        h('option', { value: 'volunteer' }, 'Wolontariusz'), h('option', { value: 'admin' }, 'Administrator'));
      roleSel.value = v.role === 'admin' ? 'admin' : 'volunteer';
      body.append(h('tr', {},
        h('td', { class: 'mono' }, v.login), h('td', {}, roleSel), h('td', {}, formatDateTime(v.created_at)),
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
    + 'Panel: ' + base + '/login?login=' + encodeURIComponent(login) + '\n'
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
    body.role = $('#vol-role').value;
    const r = await api('POST', '/api/admin/volunteers', body);
    ev.target.reset();
    await showCredentials(r.login, r.password);
    setMessage(msg, 'Konto utworzone.', 'ok');
    await loadVolunteers();
  });
});

$('#vol-body').addEventListener('change', async (ev) => {
  const sel = ev.target.closest && ev.target.closest('select[data-role-login]');
  if (!sel) return;
  const login = sel.dataset.roleLogin;
  await guard(async () => {
    try {
      await api('PATCH', '/api/admin/volunteers/' + encodeURIComponent(login), { role: sel.value });
      setMessage(msg, 'Ranga konta „' + login + '” zmieniona.', 'ok');
    } finally {
      await loadVolunteers();
    }
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

// ---------- słownik ----------
async function loadDictionary() {
  await guard(async () => {
    const d = await api('GET', '/api/admin/dictionary');
    $('#dictionary').value = JSON.stringify(d, null, 2);
    const sel = $('#pv-donor-faculty');
    sel.textContent = '';
    faculties = d.faculties || [];
    for (const f of faculties) sel.append(h('option', { value: f.code }, facultyLabel(f)));
    await loadStudents();
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

/** Komunikat błędu grafiki tuż przed polem wyniku (tworzony przy pierwszym użyciu). */
function graphicMsg(out) {
  let el = out.previousElementSibling;
  if (!el || !el.classList.contains('graphic-msg')) {
    el = h('p', { class: 'msg graphic-msg', role: 'alert', hidden: true });
    out.before(el);
  }
  return el;
}

/** Przycisk „pokaż grafikę”: wspólna obsługa postępu i błędów (makeGraphic). */
function graphicButton(btnSel, outSel, fn) {
  $(btnSel).addEventListener('click', (ev) => {
    const out = $(outSel);
    return makeGraphic(ev.currentTarget, out, graphicMsg(out), () => fn(out));
  });
}

graphicButton('#social-btn', '#social-output', async (out) => {
  const summary = await api('GET', '/api/admin/summary?date=' + encodeURIComponent($('#social-date').value));
  const fmt = $('#social-format').value;
  const canvas = await renderSocial(summary, fmt);
  const tag = summary.scope === 'day' ? summary.date : 'cala-akcja';
  await showDownload(canvas, out, 'podsumowanie-' + tag + '-' + fmt.replace(':', 'x') + '.png');
});


// ---------- liczby studentow (Puchar Dawcy PWr) ----------
async function loadStudents() {
  const d = await api('GET', '/api/admin/students');
  const counts = d.counts || {};
  $('#students-source').value = d.source || '';
  const body = $('#students-body');
  body.textContent = '';
  for (const f of faculties) {
    if (f.code === 'INNE') continue;
    const input = h('input', { type: 'number', min: '1', max: '100000', step: '1', 'data-code': f.code, 'aria-label': 'Liczba studentów: ' + facultyLabel(f) });
    if (counts[f.code] !== null && counts[f.code] !== undefined) input.value = counts[f.code];
    body.append(h('tr', {}, h('td', {}, facultyLabel(f)), h('td', {}, input)));
  }
}

$('#students-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await guard(async () => {
    const counts = {};
    for (const input of document.querySelectorAll('#students-body input[data-code]')) {
      counts[input.dataset.code] = input.value.trim() === '' ? null : Number(input.value);
    }
    await api('PUT', '/api/admin/students', { source: $('#students-source').value.trim(), counts });
    setMessage(msg, 'Liczby studentów zapisane.', 'ok');
    await loadStudents();
  });
});

// ---------- trafienia 10/10 ----------
let allWins = [];

function renderWins() {
  const q = $('#wins-filter').value.trim().toUpperCase();
  const rows = allWins.filter((w) => !q || String(w.token).toUpperCase().includes(q));
  const body = $('#wins-body');
  body.textContent = '';
  for (const w of rows) {
    body.append(h('tr', {}, h('td', {}, w.seq), h('td', { class: 'mono' }, w.token), h('td', {}, genotypeCell(w.genotype)),
      h('td', {}, w.booth_name || w.booth_id), h('td', {}, formatWarsaw(w.won_at)),
      h('td', {}, w.submitted_at
        ? h('span', { class: 'status-tag tag-used' }, 'wykorzystany ' + formatWarsaw(w.submitted_at))
        : h('span', { class: 'status-tag tag-active' }, 'niewykorzystany'))));
  }
  $('#wins-empty').hidden = rows.length > 0;
  $('#wins-empty').textContent = allWins.length ? 'Brak trafień pasujących do filtra.' : 'Brak trafień.';
}

function genotypeCell(g) {
  const el = h('div', { class: 'genotype genotype-mini', 'aria-label': 'Genotyp' });
  renderGenotype(el, g);
  return el;
}

async function loadWins() {
  await guard(async () => {
    const r = await api('GET', '/api/admin/wins');
    allWins = r.wins || [];
    $('#wins-count').textContent = 'Prawdziwych trafień 10/10: ' + r.count;
    renderWins();
  });
}
$('#wins-filter').addEventListener('input', renderWins);
$('#wins-refresh').addEventListener('click', loadWins);

// ---------- partnerzy ----------
let partnerIds = [];

async function loadPartners() {
  await guard(async () => {
    const list = await api('GET', '/api/partners');
    const ul = $('#partners-list');
    ul.textContent = '';
    $('#partners-empty').hidden = list.length > 0;
    partnerIds = list.map((p) => p.id);
    list.forEach((p, i) => {
      ul.append(h('li', { class: 'partner-item' },
        h('img', { src: p.url, alt: p.name }), h('div', {}, (i + 1) + '. ' + p.name),
        h('div', { class: 'partner-actions' },
          h('button', { class: 'btn btn-small', type: 'button', 'data-move': 'up', 'data-partner': p.id, disabled: i === 0, 'aria-label': 'Przesuń wcześniej: ' + p.name }, icon('ti-arrow-up')),
          h('button', { class: 'btn btn-small', type: 'button', 'data-move': 'down', 'data-partner': p.id, disabled: i === list.length - 1, 'aria-label': 'Przesuń później: ' + p.name }, icon('ti-arrow-down')),
          h('button', { class: 'btn btn-small', type: 'button', 'data-partner': p.id }, icon('ti-trash'), 'Usuń'))));
    });
  });
}

function readBase64(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(',')[1] || '');
    fr.onerror = () => reject(new Error('Nie udało się odczytać pliku.'));
    fr.readAsDataURL(file);
  });
}

$('#partner-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await guard(async () => {
    const file = $('#partner-file').files[0];
    if (!file) throw new Error('Wybierz plik z logo.');
    if (file.size > 1.5 * 1024 * 1024) throw new Error('Plik jest za duży (maksymalnie 1,5 MB).');
    const data = await readBase64(file);
    await api('POST', '/api/admin/partners', { name: $('#partner-name').value.trim(), filename: file.name, data_base64: data });
    ev.target.reset();
    setMessage(msg, 'Partner dodany.', 'ok');
    await loadPartners();
  });
});

$('#partners-list').addEventListener('click', async (ev) => {
  const btn = ev.target.closest && ev.target.closest('button[data-partner]');
  if (!btn) return;
  if (btn.dataset.move) {
    const i = partnerIds.indexOf(Number(btn.dataset.partner));
    const j = btn.dataset.move === 'up' ? i - 1 : i + 1;
    if (i < 0 || j < 0 || j >= partnerIds.length) return;
    const ids = partnerIds.slice();
    [ids[i], ids[j]] = [ids[j], ids[i]];
    await guard(async () => {
      await api('PUT', '/api/admin/partners/order', { ids });
      await loadPartners();
    });
    return;
  }
  if (!confirm('Usunąć tego partnera z grafik?')) return;
  await guard(async () => {
    await api('DELETE', '/api/admin/partners/' + encodeURIComponent(btn.dataset.partner));
    await loadPartners();
  });
});

// ---------- ustawienia ----------
/** ISO "RRRR-MM-DDTGG:MM" (czas Warsaw) -> "11.12.2026, 16:30" do podpowiedzi. */
function deadlineText(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(v || '');
  return m ? m[3] + '.' + m[2] + '.' + m[1] + ', ' + m[4] : '';
}

function fillDeadline(inputSel, hintSel, d) {
  $(inputSel).value = d && d.custom ? d.value : '';
  $(hintSel).textContent = d
    ? (d.custom ? 'Ustawiony w panelu: ' + deadlineText(d.value) + '. ' : 'Obowiązuje domyślny termin. ') + 'Domyślnie: ' + deadlineText(d.default) + '. Wyczyść pole i zapisz, aby wrócić do domyślnego.'
    : '';
  $(inputSel).placeholder = d ? d.default : '';
}

async function loadSettings() {
  await guard(async () => {
    const st = await api('GET', '/api/admin/settings');
    $('#set-facebook').value = st.facebook_url || '';
    fillDeadline('#set-cup-deadline', '#set-cup-deadline-hint', st.cup_deadline);
    fillDeadline('#set-contest-deadline', '#set-contest-deadline-hint', st.contest_deadline);
  });
}

$('#settings-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await guard(async () => {
    const url = $('#set-facebook').value.trim();
    if (url && !url.startsWith('https://')) throw new Error('Adres Facebooka musi zaczynać się od https://.');
    const st = await api('PUT', '/api/admin/settings', {
      facebook_url: url,
      cup_deadline: $('#set-cup-deadline').value || '',
      contest_deadline: $('#set-contest-deadline').value || '',
    });
    $('#set-facebook').value = st.facebook_url || '';
    fillDeadline('#set-cup-deadline', '#set-cup-deadline-hint', st.cup_deadline);
    fillDeadline('#set-contest-deadline', '#set-contest-deadline-hint', st.contest_deadline);
    setMessage(msg, 'Ustawienia zapisane.', 'ok');
  });
});

// ---------- podglad grafik (tylko lokalnie, bez zapisu na serwerze) ----------
graphicButton('#pv-player-btn', '#pv-player-out', async (out) => {
  const canvas = await renderPlayerCert({ nick: $('#pv-player-nick').value, genotype: '0123012301', wonAt: new Date().toISOString(),
    token: 'HG-TEST-0001', boothName: 'Stoisko testowe' });
  await showDownload(canvas, out, 'podglad-certyfikat-gracza.png');
});

graphicButton('#pv-donor-btn', '#pv-donor-out', async (out) => {
  const sel = $('#pv-donor-faculty');
  const fac = faculties.find((f) => f.code === sel.value);
  const facultyName = fac && fac.code !== 'INNE' ? fac.name : '';
  const canvas = await renderDonorCert({ name: $('#pv-donor-name').value, facultyName, category: $('#pv-donor-kind').value });
  await showDownload(canvas, out, 'podglad-certyfikat-dawcy.png');
});

graphicButton('#pv-result-btn', '#pv-result-out', async (out) => {
  const best = Math.max(0, Math.min(10, Number($('#pv-result-best').value) || 0));
  const canvas = await renderResultCert({ nick: $('#pv-result-nick').value, best, boothName: 'Stoisko testowe', date: new Date().toISOString() });
  await showDownload(canvas, out, 'podglad-wynik-symulatora.png');
});

// ---------- testy ----------
const T = '/api/admin/test/';

function fillBoothSelects() {
  for (const [id, withEmpty] of [['#t-booth', false], ['#t-fake-booth', true]]) {
    const sel = $(id);
    const cur = sel.value;
    sel.textContent = '';
    if (withEmpty) sel.append(h('option', { value: '' }, 'losowe'));
    for (const b of booths) {
      if (b.is_lecture && withEmpty) continue; // sztuczne głosy: na Zajęciach nie ma wolontariusza
      sel.append(h('option', { value: b.id }, b.name + ' (' + b.id + ')'));
    }
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
    if (e.status === 401) { location.reload(); return; }
    testResult(el, e.detail || e.message, 'error');
  }
}

async function refreshTestStatus() {
  const el = $('#t-status');
  try {
    const st = await api('GET', T + 'status');
    el.textContent = (st.game_session ? 'Sesja gry: jest' : 'Sesja gry: brak (otwórz link do symulatora w tej przeglądarce)')
      + ' · Uzbrojone 10/10: ' + (st.armed ? 'tak' : 'nie')
      + ' · Pozostałe próby: ' + (st.attempts_left === null ? '-' : st.attempts_left);
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    el.textContent = 'Błąd: ' + (e.detail || e.message);
  }
}
$('#t-refresh').addEventListener('click', refreshTestStatus);

$('#t-arm').addEventListener('click', () => runTest($('#t-arm-result'), async () => {
  await api('POST', T + 'arm-win');
  testResult($('#t-arm-result'), 'Uzbrojone: następna próba w tej przeglądarce da 10/10. Otwórz symulator przez „Link do symulatora”, wybierz stoisko i kliknij „Sprawdź parametry”.', 'ok');
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
  testResult($('#t-fake-result'), 'Dodano testowych punktów: ' + r.created + '.', 'ok');
  await loadBooths();
}));

$('#t-wipe-confirm').addEventListener('input', () => {
  $('#t-wipe').disabled = $('#t-wipe-confirm').value.trim() !== 'USUŃ';
});

$('#t-wipe').addEventListener('click', () => runTest($('#t-wipe-result'), async () => {
  if (!confirm('Na pewno usunąć wszystkie punkty i dane graczy? Tej operacji nie można cofnąć.')) return;
  await api('POST', T + 'wipe', { confirm: $('#t-wipe-confirm').value.trim() });
  $('#t-wipe-confirm').value = '';
  $('#t-wipe').disabled = true;
  testResult($('#t-wipe-result'), 'Dane testowe wyczyszczone. Stoiska dostały nowe genotypy.', 'ok');
  await Promise.all([loadBooths(), loadDays(), refreshTestStatus()]);
}));

// ---------- weryfikacja Tokenu Losu (Komisja Konkursowa, §6.2 regulaminu) ----------
let checkedToken = null;

function checkLine(el, ok, text) {
  el.textContent = '';
  el.className = ok === null ? '' : ok ? 'check-ok' : 'check-bad';
  el.append(icon(ok === null ? 'ti-info-circle' : ok ? 'ti-circle-check' : 'ti-circle-x'), ' ' + text);
}

function showToken(r) {
  checkedToken = r.exists ? r.token : null;
  $('#token-result').hidden = false;
  checkLine($('#tc-exists'), r.exists, r.exists ? '1. Token istnieje w rejestrze wygranych 10/10.' : '1. Tokenu nie ma w rejestrze wygranych 10/10 (' + r.token + ').');
  const g = $('#token-genotype');
  g.hidden = !r.exists;
  if (r.exists) renderGenotype(g, r.genotype);
  checkLine($('#tc-pattern'), null, r.exists
    ? '2. Wzór i data z rejestru (porównaj z grafiką): ' + formatWarsaw(r.won_at) + ', stoisko: ' + (r.booth_name || '-') + '.'
    : '2. Brak wzoru i daty do porównania.');
  checkLine($('#tc-unused'), r.exists ? !r.submitted_at : false, r.exists
    ? (r.submitted_at ? '3. Token był już wykorzystany w zgłoszeniu (' + formatWarsaw(r.submitted_at) + ').' : '3. Token nie został wykorzystany we wcześniejszym zgłoszeniu.')
    : '3. Nie dotyczy.');
  $('#token-meta').textContent = r.exists ? 'Token: ' + r.token : '';
  $('#token-submit').hidden = !(r.exists && !r.submitted_at);
  $('#token-unsubmit').hidden = !(r.exists && r.submitted_at);
}

async function lookupToken(value) {
  await guard(async () => {
    showToken(await api('GET', '/api/admin/tokens/' + encodeURIComponent(value)));
  });
}

$('#token-form').addEventListener('submit', (ev) => {
  ev.preventDefault();
  lookupToken($('#token-input').value);
});

$('#token-submit').addEventListener('click', async () => {
  if (!checkedToken) return;
  await guard(async () => {
    await api('POST', '/api/admin/tokens/' + encodeURIComponent(checkedToken) + '/submit');
    setMessage(msg, 'Token oznaczony jako wykorzystany.', 'ok');
    await Promise.all([lookupToken(checkedToken), loadWins()]);
  });
});

$('#token-unsubmit').addEventListener('click', async () => {
  if (!checkedToken) return;
  if (!confirm('Cofnąć oznaczenie tokenu jako wykorzystanego?')) return;
  await guard(async () => {
    await api('POST', '/api/admin/tokens/' + encodeURIComponent(checkedToken) + '/unsubmit');
    setMessage(msg, 'Oznaczenie cofnięte.', 'ok');
    await Promise.all([lookupToken(checkedToken), loadWins()]);
  });
});

// ---------- regulaminy i dokumenty ----------
const legalForm = $('#legal-form');
const legalMsg = $('#legal-msg');
let legalEditing = null; // slug edytowanego dokumentu; null = nowy

async function loadLegal() {
  await guard(async () => {
    const docs = await api('GET', '/api/admin/legal');
    const body = $('#legal-body');
    body.textContent = '';
    for (const d of docs) {
      body.append(h('tr', {},
        h('td', {}, d.title), h('td', { class: 'mono' }, d.slug), h('td', {}, 'v' + d.version),
        h('td', {}, formatWarsaw(d.updated_at)), h('td', {}, d.published ? 'tak' : 'nie'),
        h('td', { class: 'actions' },
          h('button', { class: 'btn btn-small', type: 'button', 'data-legal': 'edit', 'data-slug': d.slug }, icon('ti-pencil'), 'Edytuj'),
          h('a', { class: 'btn btn-small', href: '/dokumenty/' + encodeURIComponent(d.slug), target: '_blank', rel: 'noopener' }, icon('ti-external-link'), 'Otwórz'),
          d.base ? '' : h('button', { class: 'btn btn-small', type: 'button', 'data-legal': 'delete', 'data-slug': d.slug }, icon('ti-trash'), 'Usuń'))));
    }
  });
}

function openLegalEditor(doc) {
  legalEditing = doc ? doc.slug : null;
  legalForm.hidden = false;
  $('#legal-form-title').textContent = doc ? 'Edycja: ' + doc.title + ' (wersja ' + doc.version + ')' : 'Nowy dokument';
  $('#legal-slug-wrap').hidden = !!doc;
  $('#legal-slug').required = !doc;
  $('#legal-slug').value = doc ? doc.slug : '';
  $('#legal-title').value = doc ? doc.title : '';
  $('#legal-body-md').value = doc ? doc.body_md : '';
  $('#legal-sort').value = doc ? doc.sort : 0;
  $('#legal-sort').disabled = !doc;
  $('#legal-published').value = !doc || doc.published ? '1' : '0';
  $('#legal-published').disabled = !doc || !!doc.base;
  $('#legal-preview').hidden = true;
  setMessage(legalMsg, '');
  const versions = doc ? doc.versions || [] : [];
  $('#legal-versions-wrap').hidden = versions.length === 0;
  const ul = $('#legal-versions');
  ul.textContent = '';
  for (const v of versions) {
    ul.append(h('li', {}, 'Wersja ' + v.version + ': ' + v.title + ' (zastąpiona ' + formatWarsaw(v.saved_at) + (v.saved_by ? ', ' + v.saved_by : '') + ') ',
      h('button', { class: 'btn btn-small', type: 'button', 'data-version': v.version }, icon('ti-download'), 'Wczytaj do edytora')));
  }
  legalForm.scrollIntoView({ block: 'nearest' });
}

$('#legal-new').addEventListener('click', () => openLegalEditor(null));
$('#legal-cancel').addEventListener('click', () => { legalForm.hidden = true; legalEditing = null; });

$('#legal-body').addEventListener('click', async (ev) => {
  const btn = ev.target.closest && ev.target.closest('button[data-legal]');
  if (!btn) return;
  const slug = btn.dataset.slug;
  await guard(async () => {
    if (btn.dataset.legal === 'edit') {
      openLegalEditor(await api('GET', '/api/admin/legal/' + encodeURIComponent(slug)));
    } else {
      if (!confirm('Usunąć dokument „' + slug + '” razem z historią wersji? Tej operacji nie można cofnąć.')) return;
      await api('DELETE', '/api/admin/legal/' + encodeURIComponent(slug));
      if (legalEditing === slug) legalForm.hidden = true;
      setMessage(msg, 'Dokument usunięty.', 'ok');
      await loadLegal();
    }
  });
});

$('#legal-versions').addEventListener('click', async (ev) => {
  const btn = ev.target.closest && ev.target.closest('button[data-version]');
  if (!btn || !legalEditing) return;
  await guard(async () => {
    const v = await api('GET', '/api/admin/legal/' + encodeURIComponent(legalEditing) + '/versions/' + encodeURIComponent(btn.dataset.version));
    $('#legal-title').value = v.title;
    $('#legal-body-md').value = v.body_md;
    setMessage(legalMsg, 'Wczytano wersję ' + v.version + ' do edytora. Zapisz, żeby ją przywrócić jako nową wersję.', 'info');
  }, legalMsg);
});

$('#legal-preview-btn').addEventListener('click', async () => {
  await guard(async () => {
    const r = await api('POST', '/api/admin/legal/preview', { body_md: $('#legal-body-md').value });
    const box = $('#legal-preview');
    box.innerHTML = r.html; // HTML z serwera: Markdown bez surowego HTML
    box.hidden = false;
  }, legalMsg);
});

legalForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await guard(async () => {
    const title = $('#legal-title').value;
    const body_md = $('#legal-body-md').value;
    let done;
    if (legalEditing === null) {
      const r = await api('POST', '/api/admin/legal', { slug: $('#legal-slug').value.trim(), title, body_md });
      legalEditing = r.slug;
      done = 'Dokument utworzony.';
    } else {
      const r = await api('PUT', '/api/admin/legal/' + encodeURIComponent(legalEditing), {
        title, body_md, sort: Number($('#legal-sort').value) || 0, published: $('#legal-published').value === '1' });
      done = 'Zapisano. Wersja ' + r.version + ', ostatnia zmiana ' + formatWarsaw(r.updated_at) + '.';
    }
    await loadLegal();
    openLegalEditor(await api('GET', '/api/admin/legal/' + encodeURIComponent(legalEditing)));
    setMessage(legalMsg, done, 'ok');
  }, legalMsg);
});
