// Czesc panelu dla wolontariusza (kody i liczniki stoiska). Logowanie i wybor stoiska robi login.js.
import { api, $, h, icon, setMessage, formatTime, formatDateTime, qrUrl } from './common.js';

const msg = $('#panel-msg');
const STATUS_PL = { ACTIVE: 'aktywny', USED: 'użyty', EXPIRED: 'wygasły' };
const KIND_PL = { potential: 'potencjalny', actual: 'faktyczny', promo: 'dodatkowe losy' };
const CODE_LABEL = { potential: 'Kod rejestracyjny', actual: 'Kod dawcy faktycznego', promo: 'Kod Dodatkowe losy' };
let refreshTimer = null;
let ctx = { role: 'volunteer', boothId: '' };
let wired = false;

function show(id, on) { $('#' + id).hidden = !on; }

function renderCodes(codes) {
  const body = $('#vcodes-body');
  body.textContent = '';
  $('#vcodes-empty').hidden = codes.length > 0;
  for (const c of codes) {
    const cancel = c.status === 'ACTIVE'
      ? h('button', { class: 'btn btn-small', type: 'button', 'data-cancel': c.code }, icon('ti-x'), 'Anuluj')
      : '';
    body.append(h('tr', { class: 'code-' + c.status.toLowerCase() },
      h('td', { class: 'mono' }, c.code),
      h('td', {}, KIND_PL[c.kind] || c.kind),
      h('td', {}, h('span', { class: 'status-tag tag-' + c.status.toLowerCase() }, STATUS_PL[c.status] || c.status)),
      h('td', {}, formatDateTime(c.created_at)),
      h('td', {}, formatTime(c.expires_at)),
      h('td', {}, cancel)));
  }
}

const meUrl = () => '/api/volunteer/me' + (ctx.role === 'admin' && ctx.boothId ? '?booth_id=' + encodeURIComponent(ctx.boothId) : '');

async function refresh() {
  clearTimeout(refreshTimer);
  if (!ctx.boothId) return;
  try {
    const me = await api('GET', meUrl());
    $('#vol-booth-name').textContent = me.booth ? me.booth.name : '';
    $('#booth-screen-link').href = me.booth ? '/stoisko/' + encodeURIComponent(me.booth.id) : '/';
    $('#c-potential').textContent = me.registered_potential ?? 0;
    $('#c-actual').textContent = me.registered_actual ?? 0;
    $('#c-matches').textContent = me.matches_count ?? 0;
    $('#c-rolls').textContent = me.rolls_count ?? 0;
    renderCodes(me.codes || []);
    refreshTimer = setTimeout(refresh, 15000);
  } catch (e) {
    if (e.status === 401) { location.reload(); return; }
    setMessage(msg, e.detail || e.message, 'error');
    refreshTimer = setTimeout(refresh, 15000);
  }
}

function wire() {
  if (wired) return;
  wired = true;

  // kind: 'potential' | 'actual' (z formularza) albo 'promo' (przycisk Dodatkowe losy)
  async function generate(kind) {
    const buttons = [$('#gen-btn'), $('#promo-btn')];
    for (const x of buttons) x.disabled = true;
    setMessage(msg, '');
    try {
      const body = ctx.role === 'admin' ? { booth_id: ctx.boothId } : {};
      body.kind = kind;
      if (kind === 'actual') {
        body.card_number = $('#card-number').value;
        body.card_date = $('#card-date').value;
        if (!body.card_number.trim() || !body.card_date) throw Object.assign(new Error('Podaj numer legitymacji i datę jej wydania.'), { detail: 'Podaj numer legitymacji i datę jej wydania.' });
      }
      const r = await api('POST', '/api/volunteer/generate-code', body);
      $('#code-big').textContent = r.code;
      $('#code-qr').src = qrUrl(r.confirm_path);
      $('#code-expires').textContent = formatTime(r.expires_at);
      $('#code-kind-label').textContent = CODE_LABEL[r.kind] || 'Kod rejestracyjny';
      if (r.kind === 'actual') { $('#card-number').value = ''; $('#card-date').value = ''; }
      show('code-box', true);
      await refresh();
    } catch (e) {
      setMessage(msg, e.detail || e.message, 'error');
    } finally {
      for (const x of buttons) x.disabled = false;
    }
  }

  $('#gen-btn').addEventListener('click', () => generate($('#code-kind').value));
  $('#promo-btn').addEventListener('click', () => generate('promo'));

  $('#vcodes-body').addEventListener('click', async (ev) => {
    const btn = ev.target.closest && ev.target.closest('[data-cancel]');
    if (!btn) return;
    try {
      await api('POST', '/api/volunteer/codes/' + encodeURIComponent(btn.getAttribute('data-cancel')) + '/cancel');
      await refresh();
    } catch (e) {
      setMessage(msg, e.detail, 'error');
    }
  });

  $('#code-kind').addEventListener('change', () => { $('#actual-fields').hidden = $('#code-kind').value !== 'actual'; });
}

/** Uruchamia (lub przelacza na inne stoisko) czesc wolontariusza. me = { role, booth: {id,name}|null }. */
export function initVolunteer(me) {
  wire();
  const boothId = me && me.booth ? me.booth.id : '';
  if (boothId !== ctx.boothId) show('code-box', false);
  ctx = { role: me ? me.role : 'volunteer', boothId };
  if (!boothId) {
    clearTimeout(refreshTimer);
    return Promise.resolve();
  }
  return refresh();
}

export function stopVolunteer() {
  clearTimeout(refreshTimer);
  show('code-box', false);
  ctx = { role: 'volunteer', boothId: '' };
}
