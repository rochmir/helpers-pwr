// Czesc panelu dla wolontariusza (tokeny rejestracyjne i liczniki stoiska). Logowanie i wybor stoiska robi login.js.
import { api, $, h, icon, setMessage, formatTime, formatDateTime, qrUrl } from './common.js';

const msg = $('#panel-msg');
const STATUS_PL = { ACTIVE: 'aktywny', USED: 'użyty', EXPIRED: 'wygasły' };
const KIND_PL = { potential: 'nowy dawca', actual: 'dawca faktyczny' };
const CODE_LABEL = { potential: 'Token rejestracyjny (kod OTP)', actual: 'Token rejestracyjny: dawca faktyczny (kod OTP)' };
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
    const note = $('#cup-closed-note');
    note.hidden = !me.cup_closed;
    note.textContent = me.cup_closed ? me.cup_closed_message : '';
    $('#gen-btn').disabled = !!me.cup_closed;
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

  // kind: 'potential' (nowy dawca) albo 'actual' (dawca faktyczny z okazana legitymacja; numeru nie zapisujemy)
  async function generate(kind) {
    const btn = $('#gen-btn');
    btn.disabled = true;
    setMessage(msg, '');
    try {
      const body = ctx.role === 'admin' ? { booth_id: ctx.boothId } : {};
      body.kind = kind;
      const r = await api('POST', '/api/volunteer/generate-code', body);
      $('#code-big').textContent = r.code;
      $('#code-qr').src = qrUrl(r.confirm_path);
      $('#code-expires').textContent = formatTime(r.expires_at);
      $('#code-kind-label').textContent = CODE_LABEL[r.kind] || CODE_LABEL.potential;
      show('code-box', true);
      await refresh();
    } catch (e) {
      setMessage(msg, e.detail || e.message, 'error');
    } finally {
      btn.disabled = false;
    }
  }

  $('#gen-btn').addEventListener('click', () => generate($('#code-kind').value));

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
