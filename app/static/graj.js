import { api, $, h, formatDateRange, setMessage, storageGet, storageSet, storageRemove, loadTurnstile, requireToken, sleep, shapeEl } from './common.js';
import { renderPlayerCert, showDownload } from './cert.js';
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
let won = null; // { genotype, at } trafienia 10/10 tej sesji (do certyfikatu)

function show(id, on) { $('#' + id).hidden = !on; }
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

// ---------- komunikaty wyniku (warianty losowane, bez zmyslonych statystyk) ----------
const MSG_LOW = [
  ['Nie tym razem.', 'Spróbuj jeszcze raz!'],
  ['Jeszcze daleko do pełnej zgodności.', 'Losuj ponownie, kolejna próba może być lepsza.'],
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
  note.textContent = bonus > 0 ? '(w tym ' + bonus + ' bonusowych)' : '';
  renderPips(Math.min(n, MAX_TRIES));
  const over = n <= 0;
  $('#roll-btn').hidden = over;
  $('#lever').hidden = over;
  $('#roll-btn').disabled = over;
  machine.classList.toggle('is-over', over);
  $('#end-note').hidden = !over;
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
  show('start-section', false);
  show('play-section', false);
  if (text) $('#scan-text').textContent = text;
  show('scan-section', true);
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
  const title = best > 0 ? 'Twój najlepszy wynik dziś: ' + best + '/10' : 'To już koniec na dziś.';
  setResult(title, 'To już koniec na dziś. Wróć jutro po kolejne ' + MAX_TRIES + ' prób!', 'end');
  show('bonus-hint', !storageGet('hp_bonus'));
}

function enterPlay(me) {
  show('start-section', false);
  show('scan-section', false);
  if (me.has_won) {
    if (me.won_genotype) won = { genotype: me.won_genotype, at: me.won_at };
    show('win-section', true);
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
  if (me.attempts_left <= 0) showEnd(me.best_today || 0);
}

/** Zapisuje przepustke na stoisko (token z kodu QR) i usuwa token z paska adresu. */
async function useQrToken() {
  if (!qrToken) return null;
  try {
    await api('POST', '/api/game/enter', { booth_id: boothId, t: qrToken });
    return null;
  } catch (e) {
    return e.status === 403 ? (e.detail || 'Ten kod QR wygasł. Zeskanuj ponownie kod ze stoiska.') : (e.detail || e.message);
  } finally {
    try { history.replaceState(null, '', location.pathname + '?stoisko=' + encodeURIComponent(boothId)); } catch (e) { /* ignoruj */ }
  }
}

/** /graj bez stoiska: lista stanowisk z terminami zamiast bledu. */
async function showBoothList() {
  show('booths-section', true);
  try {
    const d = await api('GET', '/api/booths/public');
    const list = $('#booth-list');
    for (const b of d.booths) {
      const label = (b.building ? b.building + ' - ' : '') + b.name;
      const range = formatDateRange(b.date_from, b.date_to);
      list.append(h('li', {}, label + (range ? ', ' + range : '')));
    }
    $('#booth-empty').hidden = d.booths.length > 0;
    if (d.hours && d.booths.length) {
      $('#booth-hours').textContent = 'Godziny: ' + d.hours;
      $('#booth-hours').hidden = false;
    }
  } catch (e) {
    $('#booth-empty').hidden = false;
  }
}

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
  try {
    let me = await api('GET', '/api/game/me');
    const problem = await useQrToken();
    if (qrToken) me = await api('GET', '/api/game/me');
    enterPlay(me);
    if (problem && me.attempts_left > 0 && me.pass_booth !== boothId) showScan(problem);
  } catch (e) {
    if (e.status === 401) {
      storageRemove('hp_game');
      show('start-section', true);
      try { ts = await loadTurnstile($('#turnstile')); } catch (err) { setMessage(msg, err.message, 'error'); }
    } else {
      setMessage(msg, e.detail, 'error');
    }
  }
}

$('#start-btn').addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  setMessage(msg, '');
  try {
    const cf = requireToken(ts);
    const s = await api('POST', '/api/game/session', { cf_turnstile: cf ?? null });
    if (s.token) storageSet('hp_game', s.token);
    const problem = await useQrToken();
    const me = qrToken ? await api('GET', '/api/game/me') : s;
    enterPlay(me);
    if (problem && me.attempts_left > 0 && me.pass_booth !== boothId) showScan(problem);
  } catch (e) {
    setMessage(msg, e.detail || e.message, 'error');
  } finally {
    if (ts) ts.reset();
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
  setResult('Losujemy…', 'Bębny się kręcą.', 'wait');

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
    if (!bestLocal || r.matches > bestLocal.matches) {
      bestLocal = { matches: r.matches, player: r.player_genotype, booth: r.booth_genotype };
    }
    machine.classList.remove('is-spinning', 'is-tense');
    if (r.win) {
      won = { genotype: r.player_genotype, at: r.won_at }; // do certyfikatu (serwer jest źródłem czasu)
      machine.classList.add('is-win');
      show('win-banner', true);
      setResult('Genotyp 10/10!', 'Jesteś bliźniakiem genetycznym!', 'win');
      confetti();
      await sleep(reduced ? 0 : 1800);
      show('win-section', true);
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
    if (left !== null) setAttempts(left, r ? r.bonus_attempts : 0);
    else rollBtn.disabled = false;
  }
}

$('#roll-btn').addEventListener('click', roll);
$('#lever').addEventListener('click', roll);

$('#cert-btn').addEventListener('click', async () => {
  const canvas = await renderPlayerCert($('#nick').value, won && won.genotype, won && won.at);
  showDownload(canvas, $('#cert-output'), 'certyfikat-hla.png');
});

init();
