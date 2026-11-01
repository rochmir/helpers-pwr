import { api, $, h, setMessage, loadTurnstile, requireToken, facultyLabel, getConfig } from './common.js';
import { renderDonorCert, showDownload } from './cert.js';
import { deviceHashes, deviceHashSupported } from './fingerprint.js';

const msg = $('#confirm-msg');
const codeEl = $('#code');
let ts = null;
let busy = false;
let closed = false; // zliczanie punktow zakonczone (CUP_DEADLINE)

function normCode() { return codeEl.value.trim().toUpperCase(); }

/** Sprawdza token na serwerze i pokazuje wynik; zwraca odpowiedz (null przy bledzie sieci). */
async function checkCode() {
  const code = normCode();
  const st = $('#code-status');
  if (!code) { st.textContent = ''; return null; }
  try {
    const r = await api('GET', '/api/donor/check-code?kod=' + encodeURIComponent(code));
    st.textContent = r.valid
      ? (r.kind === 'actual' ? 'Token dawcy faktycznego. Dziękujemy za Twój dar! ' : '')
        + 'Token poprawny' + (r.booth_name ? ', stoisko: ' + r.booth_name : '') + '.'
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
  setMessage(msg, text, 'error');
  $('#submit-btn').disabled = true;
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
    $('#submit-btn').disabled = true;
  }
  try { ts = await loadTurnstile($('#turnstile')); } catch (e) { setMessage(msg, e.message, 'error'); }
}

codeEl.addEventListener('change', checkCode);

$('#confirm-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  if (busy || closed) return;
  busy = true;
  setMessage(msg, '');
  const name = $('#donor-name').value; // tylko lokalnie
  let sent = false; // token Turnstile jest jednorazowy: reset po kazdej probie wyslania
  try {
    const chk = await checkCode();
    if (chk && !chk.valid) throw Object.assign(new Error(), { detail: 'Ten token jest nieprawidłowy, już użyty albo wygasł. Poproś wolontariusza o nowy.' });
    if (!$('#confirm-form').checkValidity()) { $('#confirm-form').reportValidity(); return; }
    const cf = requireToken(ts);
    const { base, ext } = await deviceHashes();
    sent = true;
    const r = await api('POST', '/api/donor/register', {
      code: normCode(),
      faculty: $('#faculty').value,
      device: base,
      device_ext: ext,
      cf_turnstile: cf ?? null,
    });
    $('#confirm-form').hidden = true;
    msg.hidden = true;
    $('#done-section').hidden = false;
    $('#done-text').textContent = (r.kind === 'actual' ? 'Token dawcy faktycznego przyjęty' : 'Token przyjęty') + (r.booth_name ? ' (stoisko: ' + r.booth_name + ')' : '')
      + '. Punkt został przyznany Twojemu wydziałowi w Pucharze Dawcy PWr. Poniżej Twój certyfikat.';
    const canvas = await renderDonorCert({ name, facultyName: r.faculty === 'INNE' ? '' : r.faculty_name, kind: r.kind });
    await showDownload(canvas, $('#cert-output'), 'certyfikat-dawcy-pwr.png');
  } catch (e) {
    if (e.status === 410 && /Zliczanie/.test(e.detail || '')) showClosed(e.detail);
    else setMessage(msg, e.status === 404 ? 'Nie znamy takiego tokenu. Sprawdź, czy został przepisany poprawnie.'
      : e.status === 422 ? 'Wybrany wydział jest nieprawidłowy. Wybierz go ponownie z listy.' : (e.detail || e.message), 'error');
  } finally {
    if (ts && sent) ts.reset();
    busy = false;
  }
});

init();
