import { api, $, h, setMessage, loadTurnstile, requireToken, storageSet, facultyLabel } from './common.js';
import { renderDonorCert, showDownload } from './cert.js';

const msg = $('#confirm-msg');
const codeEl = $('#code');
let dict = { faculties: [], study_years: [] };
let ts = null;
let busy = false;
let codeKind = 'potential';
const LEAD_DONOR = $('#lead-text').textContent;
const LEAD_PROMO = 'Kod Dodatkowe losy dostajesz od wolontariusza po pokazaniu posta o akcji. Wpisz go, a dostaniesz 5 dodatkowych prób w grze.';

function normCode() { return codeEl.value.trim().toUpperCase(); }

// Pola dawcy (wydzial, rok, certyfikat) nie dotycza kodu promo: ukryte i wylaczone, by nie blokowaly walidacji.
function applyKind(kind) {
  codeKind = kind;
  const promo = kind === 'promo';
  $('#donor-fields').hidden = promo;
  $('#faculty').disabled = promo;
  $('#study-year').disabled = promo;
  $('#lead-text').textContent = promo ? LEAD_PROMO : LEAD_DONOR;
}

/** Sprawdza kod na serwerze, ustawia widok wg rodzaju kodu i zwraca odpowiedz (null przy bledzie sieci). */
async function checkCode() {
  const code = normCode();
  const st = $('#code-status');
  if (!code) { st.textContent = ''; applyKind('potential'); return null; }
  try {
    const r = await api('GET', '/api/donor/check-code?kod=' + encodeURIComponent(code));
    applyKind(r.valid && ['actual', 'promo'].includes(r.kind) ? r.kind : 'potential');
    st.textContent = r.valid
      ? (codeKind === 'actual' ? 'Kod dawcy faktycznego. Dziękujemy za Twój dar! Dostaniesz 20 dodatkowych prób w grze. '
        : codeKind === 'promo' ? 'Kod Dodatkowe losy. Dostaniesz 5 dodatkowych prób w grze. ' : '')
        + 'Kod poprawny' + (r.booth_name ? ', stoisko: ' + r.booth_name : '') + '.'
      : 'Ten kod jest nieprawidłowy, już użyty albo wygasł. Poproś wolontariusza o nowy.';
    return r;
  } catch (e) {
    st.textContent = '';
    return null;
  }
}

async function init() {
  const q = new URLSearchParams(location.search).get('kod');
  if (q) { codeEl.value = q.trim().toUpperCase(); checkCode(); }
  try {
    dict = await api('GET', '/api/dictionary/faculties');
    for (const f of dict.faculties) $('#faculty').append(h('option', { value: f.code }, facultyLabel(f)));
    for (const y of dict.study_years) $('#study-year').append(h('option', { value: y.value }, y.label));
  } catch (e) {
    setMessage(msg, 'Nie udało się pobrać listy wydziałów: ' + e.detail, 'error');
  }
  try { ts = await loadTurnstile($('#turnstile')); } catch (e) { setMessage(msg, e.message, 'error'); }
}

codeEl.addEventListener('change', checkCode);

$('#confirm-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  if (busy) return;
  busy = true;
  setMessage(msg, '');
  const name = $('#donor-name').value; // tylko lokalnie
  let sent = false; // token Turnstile jest jednorazowy: reset po kazdej probie wyslania
  try {
    // Sciezke wybiera swieza odpowiedz check-code, nie to, czy zdazylo sie zdarzenie change.
    const chk = await checkCode();
    if (chk && !chk.valid) throw Object.assign(new Error(), { detail: 'Ten kod jest nieprawidłowy, już użyty albo wygasł. Poproś wolontariusza o nowy.' });
    if (!$('#confirm-form').checkValidity()) { $('#confirm-form').reportValidity(); return; }
    const cf = requireToken(ts);
    const promo = codeKind === 'promo';
    sent = true;
    const r = promo
      ? await api('POST', '/api/donor/redeem-promo', { code: normCode(), cf_turnstile: cf ?? null })
      : await api('POST', '/api/donor/register', {
        code: normCode(),
        faculty: $('#faculty').value,
        study_year: Number($('#study-year').value),
        cf_turnstile: cf ?? null,
      });
    $('#confirm-form').hidden = true;
    msg.hidden = true;
    $('#done-section').hidden = false;
    if (promo) {
      $('#done-title').textContent = 'Dodatkowe losy odebrane!';
      $('#done-text').textContent = 'Kod przyjęty' + (r.booth_name ? ' (stoisko: ' + r.booth_name + ')' : '') + '. Dziękujemy za pomoc w promocji akcji.';
    } else $('#done-text').textContent = (r.kind === 'actual' ? 'Kod dawcy faktycznego przyjęty' : 'Kod przyjęty') + (r.booth_name ? ' (stoisko: ' + r.booth_name + ')' : '')
      + '. Twoja rejestracja została doliczona do Bitwy Wydziałów. Poniżej Twój certyfikat.';
    if (r.token) storageSet('hp_game', r.token);
    storageSet('hp_bonus', '1');
    if (r.bonus_attempts_granted) {
      $('#bonus-title').textContent = 'Masz ' + r.bonus_attempts_granted + ' dodatkowych prób w HLA Match Maker';
      $('#bonus-text').textContent = 'Masz teraz ' + r.attempts_left + ' prób do wykorzystania. Bonusowe próby nie znikają o północy.';
      if (r.play_path) $('#bonus-play').href = r.play_path;
      $('#bonus-box').hidden = false;
    }
    if (promo) return;
    const canvas = await renderDonorCert({ name, facultyName: r.faculty === 'INNE' ? '' : r.faculty_name, kind: r.kind });
    await showDownload(canvas, $('#cert-output'), 'certyfikat-dawcy-pwr.png');
  } catch (e) {
    const map = {
      409: 'Ta legitymacja jest już zarejestrowana w systemie.',
      404: 'Nie znamy takiego kodu. Sprawdź, czy został przepisany poprawnie.',
      410: 'Ten kod został już użyty lub wygasł. Poproś wolontariusza o nowy.',
      422: 'Wybrany wydział lub rok studiów jest nieprawidłowy. Wybierz je ponownie z listy.',
    };
    setMessage(msg, map[e.status] || e.detail || e.message, 'error');
  } finally {
    if (ts && sent) ts.reset();
    busy = false;
  }
});

init();
