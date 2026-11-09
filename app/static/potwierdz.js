import { api, $, h, setMessage } from './common.js';
import { renderDonorCert, showDownload, makeGraphic } from './cert.js';

const msg = $('#state-msg');
const form = $('#vote-form');
const LABELS = { nowy: 'Nowy dawca', zarejestrowany: 'Zarejestrowany dawca', faktyczny: 'Faktyczny dawca' };
const ICONS = { nowy: 'ti-user-plus', zarejestrowany: 'ti-id-badge', faktyczny: 'ti-droplet' };
// Kody lat studiów z /api/dictionary/faculties -> układ przycisków (stopień: numery lat; reszta: pojedyncze przyciski).
const YEAR_LAYOUT = [
  { title: 'I st.', items: [['I1', '1'], ['I2', '2'], ['I3', '3'], ['I4', '4']] },
  { title: 'II st.', items: [['II1', '1'], ['II2', '2']] },
  { title: '', items: [['dr', 'Doktorat'], ['inny', 'Inne']] },
];
const submitBtn = $('#submit-btn');
const picks = { faculty: '', year: '' };
let busy = false;
let claimInfo = null; // { category, booth_name }

function showOnly(id) {
  for (const x of ['vote-form', 'post-done', 'done-section']) $('#' + x).hidden = x !== id;
}

/** Komunikat w polu stanu; bez formularza (nic do zrobienia). */
function showState(text, kind = 'info') {
  showOnly(null);
  setMessage(msg, text, kind);
}

function showForm(info) {
  claimInfo = info;
  setMessage(msg, '');
  $('#vote-label-text').textContent = (LABELS[info.category] || info.category) + (info.booth_name ? ', stoisko: ' + info.booth_name : '');
  $('#vote-icon').className = 'ti ' + (ICONS[info.category] || 'ti-droplet');
  showOnly('vote-form');
}

function showPost(r) {
  setMessage(msg, '');
  $('#post-text').textContent = 'Masz ' + r.bonus_attempts_granted + ' dodatkowych prób w HLA Match Maker'
    + (r.booth_name ? ' (stoisko: ' + r.booth_name + ')' : '') + '. Dodatkowe próby wykorzystujesz po wyczerpaniu 5 prób na dobę na danym stanowisku i nie znikają o północy.';
  if (r.play_path) $('#post-play').href = r.play_path;
  showOnly('post-done');
}

function syncSubmit() {
  submitBtn.disabled = busy || !(picks.faculty && picks.year);
}

/** Zaznacza jeden przycisk w grupie (aria-checked) i ustawia ukryte pole formularza. */
function choose(group, btn, key, value, hidden) {
  for (const b of group.querySelectorAll('[role="radio"]')) {
    b.setAttribute('aria-checked', String(b === btn));
    b.classList.toggle('on', b === btn);
  }
  picks[key] = value;
  hidden.value = value;
  syncSubmit();
}

function buildFaculties(faculties) {
  const grid = $('#faculty-grid');
  const picked = $('#faculty-picked');
  for (const f of faculties) {
    const other = f.code === 'INNE';
    const btn = h('button', { type: 'button', class: 'chip' + (other ? ' chip-other' : ''), role: 'radio', 'aria-checked': 'false',
      title: f.name },
      h('b', {}, other ? 'Inne' : f.code), other ? '' : h('small', {}, f.name));
    btn.addEventListener('click', () => {
      choose(grid, btn, 'faculty', f.code, $('#faculty'));
      picked.textContent = 'Wybrano: ' + (other ? f.name : f.code + ': ' + f.name);
    });
    grid.append(btn);
  }
}

function buildYears(years) {
  const known = new Set(years.map((y) => y.code));
  const box = $('#year-groups');
  for (const g of YEAR_LAYOUT) {
    const items = g.items.filter(([code]) => known.has(code));
    if (!items.length) continue;
    const row = h('div', { class: 'chip-grid year-row', role: 'radiogroup', 'aria-label': g.title || 'Rok studiów' });
    if (g.title) row.append(h('span', { class: 'year-title' }, g.title));
    for (const [code, text] of items) {
      const btn = h('button', { type: 'button', class: 'chip chip-year', role: 'radio', 'aria-checked': 'false' }, text);
      btn.addEventListener('click', () => choose(box, btn, 'year', code, $('#study-year')));
      row.append(btn);
    }
    box.append(row);
  }
}

async function init() {
  let dict = { faculties: [], study_years: [] };
  try {
    dict = await api('GET', '/api/dictionary/faculties');
  } catch (e) {
    setMessage(msg, 'Nie udało się pobrać listy wydziałów: ' + e.detail, 'error');
  }
  buildFaculties(dict.faculties);
  buildYears(dict.study_years || []);

  const t = new URLSearchParams(location.search).get('t');
  try {
    if (t) {
      let r;
      try {
        r = await api('POST', '/api/cup/claim', { t });
      } finally {
        // Token ma zniknąć z paska adresu zawsze (historia, zrzuty ekranu, udostępnianie linku).
        try { history.replaceState(null, '', '/potwierdz'); } catch (e) { /* ignoruj */ }
      }
      if (r.kind === 'post') showPost(r);
      else showForm({ category: r.category, booth_name: r.booth_name });
      return;
    }
    const me = await api('GET', '/api/cup/me');
    if (me.voted) showState('Twój głos w Pucharze został już oddany. Dziękujemy!', 'ok');
    else if (me.claim) showForm({ category: me.claim.category, booth_name: me.claim.booth_name });
    else showState('Zeskanuj kod QR u wolontariusza na stoisku Helpers\' Generation', 'info');
  } catch (e) {
    showState(e.detail || e.message, 'error');
  }
}

form.addEventListener('submit', (ev) => {
  ev.preventDefault();
  if (busy) return;
  if (!picks.faculty || !picks.year) { setMessage(msg, 'Wybierz wydział i rok studiów.', 'error'); return; }
  busy = true;
  const name = $('#donor-name').value; // tylko lokalnie
  const btn = submitBtn;
  btn.disabled = true;
  setMessage(msg, '');
  (async () => {
    let r;
    try {
      r = await api('POST', '/api/cup/vote', { faculty: $('#faculty').value, study_year: $('#study-year').value });
    } catch (e) {
      // Błąd z serwera pokazujemy dosłownie (m.in. „Kod wygasł…”, termin Pucharu, drugi głos).
      if (e.status === 403 || e.status === 409 || e.status === 410) showState(e.detail || e.message, 'error');
      else setMessage(msg, e.detail || e.message, 'error');
      busy = false;
      syncSubmit();
      return;
    }
    showOnly('done-section');
    $('#done-text').textContent = 'Głos przyjęty' + (r.booth_name ? ' (stoisko: ' + r.booth_name + ')' : '')
      + '. Punkt został przyznany Twojemu wydziałowi w Pucharze Dawcy PWr. Poniżej Twój certyfikat.';
    if (r.bonus_attempts_granted) {
      $('#bonus-title').textContent = 'Masz ' + r.bonus_attempts_granted + ' dodatkowych prób w HLA Match Maker';
      $('#bonus-text').textContent = 'To podziękowanie za udział w Pucharze Dawcy PWr. Dodatkowe próby wykorzystujesz po wyczerpaniu 5 prób na dobę na danym stanowisku i nie znikają o północy.';
      if (r.play_path) $('#bonus-play').href = r.play_path;
      $('#bonus-box').hidden = false;
    }
    // Certyfikat: błąd rysowania nie może cofać już oddanego głosu.
    const out = $('#cert-output');
    let errEl = $('#cert-error');
    if (!errEl) {
      errEl = h('p', { class: 'msg', id: 'cert-error', role: 'alert', hidden: true });
      out.before(errEl);
    }
    await makeGraphic(null, out, errEl, async () => {
      const canvas = await renderDonorCert({ name, facultyName: r.faculty === 'INNE' ? '' : r.faculty_name, category: r.category });
      await showDownload(canvas, out, 'certyfikat-dawcy-pwr.png');
    });
    busy = false;
  })();
});

init();
