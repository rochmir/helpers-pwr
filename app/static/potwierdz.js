import { api, $, h, setMessage, facultyLabel, getConfig, storageSet } from './common.js';
import { renderDonorCert, showDownload } from './cert.js';
import { deviceHashes, deviceHashSupported } from './fingerprint.js';

const msg = $('#confirm-msg');
const codeEl = $('#code');
let busy = false;
let closed = false; // zliczanie punktow zakonczone (CUP_DEADLINE); nie dotyczy kodu dodatkowych prob
let closedText = '';
let noHash = false; // brak skrotu urzadzenia: bez niego nie ma glosu w Pucharze (kod dodatkowych prob go nie wymaga)
let codeKind = 'potential';
const LEAD_DONOR = $('#lead-text').textContent;
const CONSENT_DONOR = $('#consent-text').innerHTML;
const LEAD_PROMO = 'Kod dodatkowych prób dostajesz od wolontariusza po pokazaniu posta lub story z oznaczeniem Samorządu Studenckiego PWr i dkms_pl. Wpisz go, a dostaniesz 5 dodatkowych prób w symulatorze HLA.';
const CONSENT_PROMO = 'Kod dodatkowych prób dodaje próby do Twojej sesji gry. Nie zapisujemy ani posta, ani Twoich kont w mediach społecznościowych.';

function normCode() { return codeEl.value.trim().toUpperCase(); }

/** Kod dodatkowych prob nie dotyczy Pucharu: ukrywa pola dawcy (i ich walidacje) oraz niezalezy od terminu i skrotu urzadzenia. */
function applyKind(kind) {
  codeKind = kind;
  const promo = kind === 'promo';
  $('#donor-fields').hidden = promo;
  $('#faculty').disabled = promo;
  $('#lead-text').textContent = promo ? LEAD_PROMO : LEAD_DONOR;
  $('#consent-text').innerHTML = promo ? '' : CONSENT_DONOR;
  if (promo) $('#consent-text').textContent = CONSENT_PROMO;
  $('#submit-btn').disabled = !promo && (closed || noHash);
  if (closed) {
    if (!promo) showClosedMessage();
    else if (msg.dataset.closed === '1') { setMessage(msg, ''); msg.dataset.closed = ''; }
  }
}

function showClosedMessage() {
  setMessage(msg, closedText, 'error');
  msg.dataset.closed = '1';
}

/** Sprawdza token na serwerze i pokazuje wynik; zwraca odpowiedz (null przy bledzie sieci). */
async function checkCode() {
  const code = normCode();
  const st = $('#code-status');
  if (!code) { st.textContent = ''; return null; }
  try {
    const r = await api('GET', '/api/donor/check-code?kod=' + encodeURIComponent(code));
    applyKind(r.valid && r.kind === 'promo' ? 'promo' : 'potential');
    st.textContent = r.valid
      ? (r.kind === 'promo' ? 'Kod dodatkowych prób poprawny' + (r.booth_name ? ', stoisko: ' + r.booth_name : '') + '. Dostaniesz ' + r.bonus + ' dodatkowych prób w symulatorze HLA.'
        : (r.kind === 'actual' ? 'Token dawcy faktycznego. Dziękujemy za Twój dar! ' : '')
          + 'Token poprawny' + (r.booth_name ? ', stoisko: ' + r.booth_name : '') + '. Za udział w Pucharze Dawcy PWr dostaniesz ' + r.bonus + ' dodatkowych prób w symulatorze HLA.')
      : 'Ten token jest nieprawidłowy, już użyty albo wygasł. Poproś wolontariusza o nowy.';
    return r;
  } catch (e) {
    st.textContent = '';
    return null;
  }
}

/** Po terminie zliczania punktow formularz jest wylaczony i pokazuje komunikat z serwera. */
function showClosed(text) {
  closed = true;
  closedText = text;
  applyKind(codeKind);
}

async function init() {
  const q = new URLSearchParams(location.search).get('kod');
  if (q) { codeEl.value = q.trim().toUpperCase(); checkCode(); }
  try {
    const dict = await api('GET', '/api/dictionary/faculties');
    for (const f of dict.faculties) $('#faculty').append(h('option', { value: f.code }, facultyLabel(f)));
  } catch (e) {
    setMessage(msg, 'Nie udało się pobrać listy wydziałów: ' + e.detail, 'error');
  }
  try {
    const cfg = await getConfig();
    if (cfg && cfg.cup_deadline && Date.now() >= new Date(cfg.cup_deadline).getTime()) {
      const info = await api('GET', '/api/stats/cup');
      showClosed(info.cup_closed_message || 'Zliczanie punktów zostało zakończone.');
    }
  } catch (e) { /* termin sprawdzi tez serwer przy wysylce */ }
  if (!deviceHashSupported()) {
    setMessage(msg, 'Ta przeglądarka nie pozwala obliczyć skrótu urządzenia, a bez niego nie można oddać głosu (wymagane jest bezpieczne połączenie HTTPS). Otwórz stronę w aktualnej przeglądarce, np. Chrome lub Safari.', 'error');
    noHash = true;
    applyKind(codeKind);
  }
}

codeEl.addEventListener('change', checkCode);

$('#confirm-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  if (busy || (codeKind !== 'promo' && (closed || noHash))) return;
  busy = true;
  setMessage(msg, '');
  const name = $('#donor-name').value; // tylko lokalnie
  try {
    const chk = await checkCode();
    if (chk && !chk.valid) throw Object.assign(new Error(), { detail: 'Ten token jest nieprawidłowy, już użyty albo wygasł. Poproś wolontariusza o nowy.' });
    if (!$('#confirm-form').checkValidity()) { $('#confirm-form').reportValidity(); return; }
    const promo = codeKind === 'promo';
    const { base, ext } = promo ? {} : await deviceHashes();
    const r = promo
      ? await api('POST', '/api/donor/redeem-promo', { code: normCode() })
      : await api('POST', '/api/donor/register', {
        code: normCode(),
        faculty: $('#faculty').value,
        device: base,
        device_ext: ext,
      });
    $('#confirm-form').hidden = true;
    msg.hidden = true;
    $('#done-section').hidden = false;
    if (r.token) storageSet('hp_game', r.token);
    if (r.bonus_attempts_granted) {
      $('#bonus-title').textContent = 'Masz ' + r.bonus_attempts_granted + ' dodatkowych prób w HLA Match Maker';
      $('#bonus-text').textContent = (promo ? 'Dziękujemy za pomoc w promocji akcji. ' : 'To podziękowanie za udział w Pucharze Dawcy PWr. ')
        + 'Dodatkowe próby wykorzystujesz po wyczerpaniu 5 prób na dobę na danym stanowisku i nie znikają o północy.';
      if (r.play_path) $('#bonus-play').href = r.play_path;
      $('#bonus-box').hidden = false;
    }
    if (promo) {
      $('#done-title').textContent = 'Dodatkowe próby odebrane!';
      $('#done-text').textContent = 'Kod przyjęty' + (r.booth_name ? ' (stoisko: ' + r.booth_name + ')' : '') + '.';
      return;
    }
    $('#done-text').textContent = (r.kind === 'actual' ? 'Token dawcy faktycznego przyjęty' : 'Token przyjęty') + (r.booth_name ? ' (stoisko: ' + r.booth_name + ')' : '')
      + '. Punkt został przyznany Twojemu wydziałowi w Pucharze Dawcy PWr. Poniżej Twój certyfikat.';
    const canvas = await renderDonorCert({ name, facultyName: r.faculty === 'INNE' ? '' : r.faculty_name, kind: r.kind });
    await showDownload(canvas, $('#cert-output'), 'certyfikat-dawcy-pwr.png');
  } catch (e) {
    if (e.status === 410 && /Zliczanie/.test(e.detail || '')) showClosed(e.detail);
    else setMessage(msg, e.status === 404 ? 'Nie znamy takiego tokenu. Sprawdź, czy został przepisany poprawnie.'
      : e.status === 422 ? 'Wybrany wydział jest nieprawidłowy. Wybierz go ponownie z listy.' : (e.detail || e.message), 'error');
  } finally {
    busy = false;
  }
});

init();
