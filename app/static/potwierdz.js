import { api, $, h, setMessage, facultyLabel } from './common.js';
import { renderDonorCert, showDownload, makeGraphic } from './cert.js';

const msg = $('#state-msg');
const form = $('#vote-form');
const LABELS = { nowy: 'Nowy dawca', zarejestrowany: 'Zarejestrowany dawca', faktyczny: 'Faktyczny dawca' };
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
  $('#vote-label').textContent = (LABELS[info.category] || info.category) + (info.booth_name ? ', stoisko: ' + info.booth_name : '');
  showOnly('vote-form');
}

function showPost(r) {
  setMessage(msg, '');
  $('#post-text').textContent = 'Masz ' + r.bonus_attempts_granted + ' dodatkowych prób w HLA Match Maker'
    + (r.booth_name ? ' (stoisko: ' + r.booth_name + ')' : '') + '. Dodatkowe próby wykorzystujesz po wyczerpaniu 5 prób na dobę na danym stanowisku i nie znikają o północy.';
  if (r.play_path) $('#post-play').href = r.play_path;
  showOnly('post-done');
}

async function init() {
  let dict = { faculties: [], study_years: [] };
  try {
    dict = await api('GET', '/api/dictionary/faculties');
  } catch (e) {
    setMessage(msg, 'Nie udało się pobrać listy wydziałów: ' + e.detail, 'error');
  }
  for (const f of dict.faculties) $('#faculty').append(h('option', { value: f.code }, facultyLabel(f)));
  for (const y of dict.study_years || []) $('#study-year').append(h('option', { value: y.code }, y.label));

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
  if (!form.checkValidity()) { form.reportValidity(); return; }
  busy = true;
  const name = $('#donor-name').value; // tylko lokalnie
  const btn = $('#submit-btn');
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
      btn.disabled = false;
      busy = false;
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
