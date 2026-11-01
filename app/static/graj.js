import { api, $, h, formatDateRange, formatWarsawLong, setMessage, storageGet, storageSet, storageRemove, loadTurnstile, requireToken, sleep, shapeEl, getConfig } from './common.js';
import { renderPlayerCert, renderResultCert, showDownload } from './cert.js';
import { deviceHashes, deviceHashSupported } from './fingerprint.js';
import { spinReels, buildReels, showReels, prefersReducedMotion, confetti } from './reels.js';

const params = new URLSearchParams(location.search);
const boothId = params.get('stoisko');
const qrToken = params.get('t');
const msg = $('#game-msg');
const machine = $('#machine');
const playerEl = $('#player-genotype');
const targetEl = $('#booth-genotype');
const MAX_TRIES = 5;
let ts = null;
let busy = false;
let boothGenotype = '';
let attemptsLeft = null;
let bestLocal = null; // najlepszy rzut z tej wizyty: { matches, player, booth }
let won = null; // { genotype, at, token, booth } trafienia 10/10 tej sesji (do certyfikatu)
let bestOverall = 0; // najlepszy wynik dnia (serwer + rzuty z tej wizyty)
let needSession = false; // true, gdy trzeba utworzyc sesje (Turnstile)
let pendingMe = null; // stan sesji (lub null), gdy czekamy na zgode w oknie startowym
let winShown = false; // ekran wygranej jest widoczny: okno konca nie otwiera sie samo

let legalUpdatedAt = null; // data ostatniej zmiany regulaminu konkursu / polityki (z /api/config)

/** Zgoda jest ważna, gdy zapisano ją po ostatniej zmianie dokumentów (hp_consent trzyma legal_updated_at z chwili zgody). */
const consentOk = () => {
  const v = storageGet('hp_consent');
  return !!v && (legalUpdatedAt === null || v === legalUpdatedAt);
};

function show(id, on) { $('#' + id).hidden = !on; }
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

// ---------- komunikaty wyniku (warianty losowane, bez zmyslonych statystyk) ----------
const MSG_LOW = [
  ['Nie tym razem.', 'Spróbuj jeszcze raz!'],
  ['Jeszcze daleko do pełnej zgodności.', 'Sprawdź ponownie, kolejna próba może być lepsza.'],
  ['To nie był ten genotyp.', 'Zakręć jeszcze raz i sprawdź, co wypadnie.'],
];
const MSG_MID = [
  ['Blisko!', 'Jeszcze jedna próba?'],
  ['Coraz cieplej!', 'Brakuje już tylko kilku zgodnych pozycji.'],
  ['Niewiele zabrakło.', 'Spróbuj jeszcze raz, możesz być bliźniakiem genetycznym.'],
];
const MSG_HIGH = [
  ['Tak blisko!', 'Zabrakło jednej zgodności!'],
  ['Jedna pozycja dzieli Cię od bycia bliźniakiem genetycznym!', 'Zakręć jeszcze raz.'],
];

function resultText(matches) {
  const [title, text] = pick(matches >= 9 ? MSG_HIGH : matches >= 7 ? MSG_MID : MSG_LOW);
  return { title, text: text + ' Zgodnych pozycji: ' + matches + ' z 10.' };
}

function setResult(title, text, kind) {
  const box = $('#result');
  box.hidden = !title;
  box.className = 'result' + (kind ? ' result-' + kind : '');
  $('#result-title').textContent = title || '';
  $('#result-text').textContent = text || '';
  // ponowne uruchomienie animacji wejscia
  void box.offsetWidth;
  box.classList.add('enter');
}

function renderPips(n) {
  const wrap = $('#pips');
  wrap.textContent = '';
  for (let i = 0; i < MAX_TRIES; i++) wrap.append(h('span', { class: 'pip' + (i < n ? ' full' : '') }));
}

function setAttempts(n, bonus) {
  attemptsLeft = n;
  $('#attempts-left').textContent = n;
  const note = $('#bonus-note');
  note.hidden = !(bonus > 0);
  note.textContent = bonus > 0 ? '(w tym ' + bonus + ' dodatkowych)' : '';
  renderPips(Math.min(n, MAX_TRIES));
  const over = n <= 0;
  $('#roll-btn').hidden = over;
  $('#lever').hidden = over;
  $('#roll-btn').disabled = over;
  machine.classList.toggle('is-over', over);
  $('#end-note').hidden = !over;
  $('#end-open-btn').hidden = !over;
}

function renderTarget(genotype) {
  targetEl.textContent = '';
  for (const c of String(genotype || '')) targetEl.append(shapeEl(c));
}

function markTarget(i, hit) {
  const t = targetEl.children[i];
  if (t) t.classList.add(hit ? 'match' : 'miss');
}

function setScore(n, tick) {
  const el = $('#score');
  el.textContent = n + '/10';
  if (tick) {
    el.classList.remove('tick');
    void el.offsetWidth;
    el.classList.add('tick');
  }
}

function showScan(text) {
  show('play-section', false);
  if (text) $('#scan-text').textContent = text;
  show('scan-section', true);
}

/** Grafika z wynikiem do odebrania, gdy jest jakikolwiek wynik dnia (nagrody sa tylko za najlepsze hasla w konkursie). */
function updateRewards() {
  show('result-cert-section', bestOverall >= 1);
}

/** Sekcja trafienia 10/10: Token Losu, instrukcja konkursu albo informacja o zamknieciu zgloszen, link do Facebooka. */
async function renderWin() {
  $('#win-token').textContent = (won && won.token) || '-';
  try {
    const cfg = await getConfig();
    const url = cfg && typeof cfg.facebook_url === 'string' ? cfg.facebook_url.trim() : '';
    if (url.startsWith('https://')) {
      $('#fb-link').href = url;
      show('fb-line', true);
    }
    const deadline = cfg && cfg.contest_deadline ? new Date(cfg.contest_deadline) : null;
    if (deadline && !Number.isNaN(deadline.getTime())) {
      $('#contest-deadline').textContent = formatWarsawLong(cfg.contest_deadline);
      const closed = Date.now() >= deadline.getTime();
      show('contest-open', !closed);
      show('contest-closed', closed);
    }
  } catch (e) { /* bez linku i terminu: zostaje domyslna instrukcja */ }
}

/** Ekran konca prob: najlepszy wynik dnia zamiast ostatniego rzutu. */
function showEnd(best) {
  const local = bestLocal && bestLocal.matches === best ? bestLocal : null;
  setAttempts(0, 0);
  if (local) {
    machine.hidden = false;
    renderTarget(local.booth);
    showReels(playerEl, local.player, local.booth);
    for (let i = 0; i < local.booth.length; i++) markTarget(i, local.player[i] === local.booth[i]);
    setScore(local.matches, false);
  } else {
    machine.hidden = true; // po przeladowaniu znamy tylko liczbe
  }
  bestOverall = Math.max(bestOverall, best);
  updateRewards();
  const title = best > 0 ? 'Twój najlepszy wynik dziś: ' + best + '/10' : 'To już koniec prób na tym stanowisku.';
  setResult(title, 'Limit prób na tym stanowisku na dziś wykorzystany. Zagraj na innym stanowisku albo wróć jutro.', 'end');
  // Przy wygranej gracz najpierw widzi ekran wygranej (token, Facebook); okno otwiera przyciskiem.
  if (!winShown) openEndDialog();
}

function enterPlay(me) {
  show('scan-section', false);
  if (me.pass_is_lecture) showLecture();
  bestOverall = Math.max(bestOverall, me.best_today || 0);
  if (me.has_won) {
    if (me.won_genotype) won = { genotype: me.won_genotype, at: me.won_at, token: me.won_token, booth: me.won_booth_name };
    winShown = true;
    show('win-section', true);
    renderWin();
  }
  if (me.attempts_left > 0 && me.pass_booth !== boothId) {
    showScan();
    return;
  }
  show('play-section', true);
  renderTarget(boothGenotype);
  buildReels(playerEl);
  setScore(0, false);
  setAttempts(me.attempts_left, me.bonus_attempts || 0);
  updateRewards();
  if (me.attempts_left <= 0) showEnd(me.best_today || 0);
}

/** Zapisuje przepustke na stoisko (token z kodu QR + skrot urzadzenia + zgoda) i usuwa token z paska adresu. */
async function useQrToken() {
  if (!qrToken) return null;
  try {
    const { base, ext } = await deviceHashes();
    await api('POST', '/api/game/enter', { booth_id: boothId, t: qrToken, device: base, device_ext: ext, consent: true });
    return null;
  } catch (e) {
    return e.status === 403 ? (e.detail || 'Ten kod QR wygasł. Zeskanuj ponownie kod ze stoiska.') : (e.detail || e.message);
  } finally {
    try { history.replaceState(null, '', location.pathname + '?stoisko=' + encodeURIComponent(boothId)); } catch (e) { /* ignoruj */ }
  }
}

/** Wejscie do gry po zgodzie: przepustka z kodu QR, potem stan sesji. me0 = stan sesji znany wczesniej. */
async function proceed(me0) {
  const problem = await useQrToken();
  const me = qrToken ? await api('GET', '/api/game/me') : me0;
  enterPlay(me);
  if (problem && me.attempts_left > 0 && me.pass_booth !== boothId) showScan(problem);
}

/** Wiersz listy stanowisk: "budynek - nazwa, terminy". */
function boothLine(b) {
  const label = (b.building ? b.building + ' - ' : '') + b.name;
  const range = formatDateRange(b.date_from, b.date_to);
  return label + (range ? ', ' + range : '');
}

/** Wspolne wypelnienie listy stanowisk i godzin (lista na /graj i okno konca). */
function fillBoothList(listEl, hoursEl, booths, hours) {
  listEl.textContent = '';
  for (const b of booths) listEl.append(h('li', {}, boothLine(b)));
  if (hours && booths.length) {
    hoursEl.textContent = 'Godziny: ' + hours;
    hoursEl.hidden = false;
  } else {
    hoursEl.hidden = true;
  }
}

/** /graj bez stoiska: lista stanowisk z terminami zamiast bledu. */
async function showBoothList() {
  show('booths-section', true);
  try {
    const d = await api('GET', '/api/booths/public');
    fillBoothList($('#booth-list'), $('#booth-hours'), d.booths, d.hours);
    $('#booth-empty').hidden = d.booths.length > 0;
  } catch (e) {
    $('#booth-empty').hidden = false;
  }
}

// ---------- okna: startowe i koncowe ----------
const introDlg = $('#intro-dialog');
const endDlg = $('#end-dialog');
const startMsg = $('#start-msg');
let introMode = null; // 'consent' (obowiazkowe, bez zamykania) albo 'preview' (same zasady)

/** Okno startowe. consent: zasady + zgoda + Turnstile, nie da sie go zamknac bez akceptacji; preview: sam podglad. */
function openIntro(mode) {
  if (introDlg.open || typeof introDlg.showModal !== 'function') return;
  introMode = mode;
  $('#consent-block').hidden = mode !== 'consent';
  $('#intro-ok').hidden = mode === 'consent';
  setMessage(startMsg, '');
  introDlg.showModal();
  introDlg.scrollTop = 0;
}

// Esc i ponowne otwarcie: w trybie zgody okno zostaje (Chrome po drugim Esc zamyka mimo cancel).
introDlg.addEventListener('cancel', (ev) => { if (introMode === 'consent') ev.preventDefault(); });
introDlg.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && introMode === 'consent') ev.preventDefault(); });
introDlg.addEventListener('close', () => {
  if (introMode === 'consent' && typeof introDlg.showModal === 'function') introDlg.showModal();
});

/** Daty ostatniej zmiany regulaminu konkursu i polityki prywatnosci obok linkow w oknie zgody. */
async function fillConsentDates() {
  try {
    const d = await api('GET', '/api/legal');
    for (const [slug, id] of [['regulamin-konkursu', 'consent-date-terms'], ['polityka-prywatnosci', 'consent-date-privacy']]) {
      const doc = (d.documents || []).find((x) => x.slug === slug);
      if (doc) $('#' + id).textContent = '(ostatnia zmiana: ' + formatWarsawLong(doc.updated_at) + ')';
    }
  } catch (e) { /* daty sa dodatkiem, brak nie blokuje zgody */ }
}

/** Okno startowe przed gra: withSession = trzeba jeszcze utworzyc sesje (widget Turnstile w oknie). */
async function showStart(withSession) {
  needSession = withSession;
  // Zgoda sprzed zmiany dokumentow nie obowiazuje: zaznaczamy to w oknie (pierwsza wizyta bez zgody: bez tej informacji).
  $('#consent-changed').hidden = !storageGet('hp_consent');
  fillConsentDates();
  openIntro('consent');
  if (withSession && !ts) {
    try { ts = await loadTurnstile($('#turnstile')); } catch (err) { setMessage(startMsg, err.message, 'error'); }
  }
}

/** Blok „Więcej o akcji” po wejściu ze stanowiska Zajęcia: stała treść z regulaminów plus lista stanowisk. */
let lectureShown = false;
async function showLecture() {
  if (lectureShown) return;
  lectureShown = true;
  show('lecture-section', true);
  const empty = $('#lecture-booth-empty');
  let booths = [];
  let hours = '';
  try {
    const d = await api('GET', '/api/booths/public');
    booths = d.booths || [];
    hours = d.hours || '';
  } catch (e) { /* blad listy nie blokuje reszty bloku */ }
  fillBoothList($('#lecture-booth-list'), $('#lecture-booth-hours'), booths, hours);
  empty.hidden = booths.length > 0;
}

/** Okno konca prob: najlepszy wynik dnia, inne stanowiska (bledy API nie blokuja reszty), certyfikat. */
async function openEndDialog() {
  if (endDlg.open || typeof endDlg.showModal !== 'function') return;
  const hasCert = !!won || bestOverall > 0;
  $('#end-best').textContent = bestOverall > 0 ? 'Twój najlepszy wynik dziś: ' + bestOverall + '/10.' : '';
  $('#end-best').hidden = !(bestOverall > 0);
  $('#end-cert').hidden = !hasCert;
  $('#end-cert-title').textContent = won ? 'Twój certyfikat 10/10' : 'Odbierz swój wynik';
  endDlg.showModal();
  endDlg.scrollTop = 0;
  const list = $('#end-booth-list');
  const hoursEl = $('#end-booth-hours');
  const empty = $('#end-booth-empty');
  list.textContent = '';
  hoursEl.hidden = true;
  empty.hidden = true;
  let booths = [];
  let hours = '';
  try {
    const d = await api('GET', '/api/booths/public');
    const here = $('#game-booth').textContent;
    booths = (d.booths || []).filter((b) => b.name !== here);
    hours = d.hours || '';
  } catch (e) { /* blad listy nie blokuje reszty okna */ }
  fillBoothList(list, hoursEl, booths, hours);
  empty.hidden = booths.length > 0;
}

/** Grafika z wynikiem: certyfikat 10/10 gdy sesja ma trafienie, inaczej grafika z najlepszym wynikiem. */
async function buildResultCanvas(nick, preferWin) {
  if (preferWin && won) {
    return renderPlayerCert({ nick, genotype: won.genotype, wonAt: won.at, token: won.token, boothName: won.booth || $('#game-booth').textContent });
  }
  return renderResultCert({ nick, best: bestOverall, boothName: $('#game-booth').textContent, date: new Date().toISOString() });
}

$('#rules-btn').addEventListener('click', () => openIntro('preview'));
$('#intro-ok').addEventListener('click', () => { introMode = null; introDlg.close(); });
$('#end-open-btn').addEventListener('click', openEndDialog);
$('#end-close').addEventListener('click', () => endDlg.close());
$('#end-cert-btn').addEventListener('click', async () => {
  const canvas = await buildResultCanvas($('#end-nick').value, true);
  await showDownload(canvas, $('#end-cert-output'), won ? 'certyfikat-hla.png' : 'wynik-hla.png');
});

async function init() {
  if (!boothId) {
    await showBoothList();
    return;
  }
  try {
    const b = await api('GET', '/api/booth/' + encodeURIComponent(boothId) + '/state');
    $('#game-booth').textContent = b.name;
    show('game-booth-wrap', true);
    boothGenotype = b.genotype || '';
  } catch (e) {
    setMessage(msg, e.status === 404
      ? 'Nie znamy stoiska „' + boothId + '”. Zeskanuj kod QR ze stoiska jeszcze raz.'
      : e.detail, 'error');
    return;
  }
  if (!deviceHashSupported()) {
    setMessage(msg, 'Ta przeglądarka nie pozwala obliczyć identyfikatora urządzenia, a bez niego nie można korzystać z symulatora (wymagane jest bezpieczne połączenie HTTPS). Otwórz symulator w aktualnej przeglądarce, np. Chrome lub Safari.', 'error');
    return;
  }
  try {
    const cfg = await getConfig();
    legalUpdatedAt = (cfg && cfg.legal_updated_at) || null;
  } catch (e) { legalUpdatedAt = null; }
  storageRemove('hp_intro'); // dawny znacznik okna startowego, zgoda to teraz hp_consent
  let me = null;
  try {
    me = await api('GET', '/api/game/me');
  } catch (e) {
    if (e.status !== 401) {
      setMessage(msg, e.detail || e.message, 'error');
      return;
    }
    storageRemove('hp_game');
  }
  if (!me || !consentOk()) {
    pendingMe = me;
    await showStart(!me);
    return;
  }
  try {
    await proceed(me);
  } catch (e) {
    setMessage(msg, e.detail || e.message, 'error');
  }
}

$('#start-btn').addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  const btn = $('#start-btn');
  btn.disabled = true;
  setMessage(startMsg, '');
  let me = pendingMe;
  try {
    if (needSession) {
      const cf = requireToken(ts); // przy wlaczonej captchy rzuca blad, gdy brak tokenu
      const s = await api('POST', '/api/game/session', { cf_turnstile: cf ?? null });
      if (s.token) storageSet('hp_game', s.token);
      me = s;
      needSession = false;
    }
    storageSet('hp_consent', legalUpdatedAt || '1');
  } catch (e) {
    setMessage(startMsg, e.detail || e.message, 'error');
    if (ts) ts.reset();
    btn.disabled = false;
    busy = false;
    return;
  }
  introMode = null;
  introDlg.close();
  btn.disabled = false;
  try {
    await proceed(me);
  } catch (e) {
    setMessage(msg, e.detail || e.message, 'error');
  } finally {
    busy = false;
  }
});

async function roll() {
  if (busy || attemptsLeft === null || attemptsLeft <= 0) return;
  busy = true;
  const rollBtn = $('#roll-btn');
  const reduced = prefersReducedMotion();
  let matched = 0;
  let r = null;
  let left = null;
  let leftBonus = 0;
  rollBtn.disabled = true;
  setMessage(msg, '');
  show('win-banner', false);
  machine.classList.remove('is-win', 'is-tense');
  machine.classList.add('is-spinning');
  const lever = $('#lever');
  lever.classList.add('pulled');
  setTimeout(() => lever.classList.remove('pulled'), 700);
  setScore(0, false);
  renderTarget(boothGenotype);
  setResult('Sprawdzamy…', 'Bębny się kręcą.', 'wait');

  // Zapytanie idzie od razu; bebny kreca sie rownolegle i zaczynaja hamowac po odpowiedzi.
  const request = api('POST', '/api/game/roll', { booth_id: boothId });
  request.catch(() => {});
  const target = request.then((resp) => {
    r = resp;
    boothGenotype = resp.booth_genotype;
    renderTarget(boothGenotype);
    return resp.player_genotype;
  });

  try {
    await spinReels(playerEl, target, {
      reduced,
      tension: () => !!r && r.matches >= 8,
      onTension: (on) => {
        machine.classList.toggle('is-tense', on);
        if (on) setResult('Ostatnie bębny…', 'Jeszcze chwila.', 'wait');
      },
      onStop: (i, symbol, reelEl) => {
        const hit = symbol === boothGenotype[i];
        reelEl.classList.add(hit ? 'match' : 'miss', 'pop');
        markTarget(i, hit);
        if (hit) matched++;
        setScore(matched, true);
      },
    });
    setScore(r.matches, false);
    left = r.attempts_left;
    leftBonus = r.bonus_attempts || 0;
    if (!bestLocal || r.matches > bestLocal.matches) {
      bestLocal = { matches: r.matches, player: r.player_genotype, booth: r.booth_genotype };
    }
    machine.classList.remove('is-spinning', 'is-tense');
    bestOverall = Math.max(bestOverall, r.best_today || 0, bestLocal.matches);
    updateRewards();
    if (r.win) {
      won = { genotype: r.player_genotype, at: r.won_at, token: r.won_token, booth: r.won_booth_name }; // do certyfikatu (serwer jest zrodlem czasu)
      machine.classList.add('is-win');
      show('win-banner', true);
      setResult('Genotyp 10/10!', 'Jesteś bliźniakiem genetycznym!', 'win');
      confetti();
      await sleep(reduced ? 0 : 1800);
      winShown = true;
      show('win-section', true);
      renderWin();
      $('#win-section').scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
    } else if (left <= 0) {
      // Ostatni rzut nie jest wynikiem dnia: pokazujemy najlepszy.
      await sleep(reduced ? 300 : 1100);
      showEnd(Math.max(r.best_today || 0, bestLocal.matches));
    } else {
      const t = resultText(r.matches);
      setResult(t.title, t.text, r.matches >= 9 ? 'high' : r.matches >= 7 ? 'mid' : 'low');
    }
    show('after-roll', true);
  } catch (e) {
    machine.classList.remove('is-spinning', 'is-tense');
    if (e.status === 429) {
      left = 0;
      showEnd((e.data && e.data.best_today) || 0);
    } else if (e.status === 403) {
      showScan();
    } else if (e.status === 401) {
      storageRemove('hp_game');
      location.reload();
      return;
    } else {
      setResult('', '');
      setMessage(msg, e.detail || e.message, 'error');
    }
  } finally {
    busy = false;
    if (left !== null) setAttempts(left, leftBonus);
    else rollBtn.disabled = false;
  }
}

$('#roll-btn').addEventListener('click', roll);
$('#lever').addEventListener('click', roll);

$('#cert-btn').addEventListener('click', async () => {
  const w = won || {};
  const canvas = await renderPlayerCert({ nick: $('#nick').value, genotype: w.genotype, wonAt: w.at, token: w.token, boothName: w.booth || $('#game-booth').textContent });
  await showDownload(canvas, $('#cert-output'), 'certyfikat-hla.png');
});

$('#result-btn').addEventListener('click', async () => {
  const canvas = await buildResultCanvas($('#result-nick').value, false);
  await showDownload(canvas, $('#result-output'), 'wynik-hla.png');
});

init();
