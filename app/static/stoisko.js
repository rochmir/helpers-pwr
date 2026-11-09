import { api, $, renderGenotype, qrUrl } from './common.js';
import { spinReels, prefersReducedMotion, confetti } from './reels.js';

const pathParts = location.pathname.replace(/\/+$/, '').split('/');
const lastPart = decodeURIComponent(pathParts.pop() || '');
// /zajecia/{token}: ekran stanowiska Zajęcia dla prowadzących, bez logowania (token w adresie zastępuje cookie personelu).
const isLectureScreen = pathParts.pop() === 'zajecia';
const boothId = isLectureScreen ? 'zajecia' : lastPart;
const screenToken = isLectureScreen ? lastPart : null;
const POLL_MS = 2500;
const OVERLAY_MS = 7000; // czas pokazania overlay'a od startu animacji

let shownGenotype = null;
let pendingGenotype = null;
let overlayTimer = null;
let celebrationId = 0;
let qrPath = null;
let qrChangeAt = 0; // znacznik czasu (ms) zmiany kodu QR
const QR_PERIOD_S = 60;

function showState(s) {
  $('#booth-name').textContent = s.name || 'Helpers’ Generation';
  $('#matches-count').textContent = s.matches_count;
  $('#rolls-count').textContent = s.rolls_count;
  // Ważny link do gry dostaje tylko zalogowany personel; bez sesji pokazujemy zachętę do logowania.
  $('#qr-login').hidden = !!s.play_path;
  if (!isLectureScreen) {
    $('#qr-login a').href = '/login?next=' + encodeURIComponent(location.pathname);
    $('#qr-login a').lastChild.textContent = ' Wybierz to stoisko w panelu wolontariusza';
  }
  if (isLectureScreen && !s.play_path) {
    // Link został zmieniony przez administratora: logowanie nic tu nie da, trzeba nowego linku.
    $('.qr-login-title').textContent = 'Ten link do ekranu nie działa';
    $('#qr-login p:not(.qr-login-title)').textContent = 'Poproś administratora akcji o nowy link do ekranu Zajęć.';
    $('#qr-login a').hidden = true;
  }
  $('#qr-timer').hidden = !s.play_path;
  if (!s.play_path) {
    qrPath = null;
    $('#qr').hidden = true;
  } else {
    qrChangeAt = Date.now() + (s.qr_seconds_left || QR_PERIOD_S) * 1000;
    if (s.play_path !== qrPath) {
      qrPath = s.play_path;
      const img = $('#qr');
      img.src = qrUrl(s.play_path);
      img.hidden = false;
    }
  }
  if (shownGenotype === null) {
    shownGenotype = s.genotype;
    renderGenotype($('#genotype'), s.genotype);
  } else if (s.genotype !== shownGenotype && s.genotype !== pendingGenotype) {
    pendingGenotype = s.genotype;
    celebrate(s.genotype);
  }
}

function celebrate(newGenotype) {
  const overlay = $('#overlay');
  const id = ++celebrationId;
  overlay.classList.remove('done');
  overlay.hidden = false;
  clearTimeout(overlayTimer);
  // Kreci bebnami i zatrzymuje je na nowym genotypie; potem trzyma wynik na ekranie.
  spinReels($('#overlay-reels'), newGenotype, { speed: 1 })
    .then(() => {
      if (id !== celebrationId) return;
      overlay.classList.add('done');
      confetti(overlay, { count: 110, lifeMs: 6000 });
    })
    .catch(() => {});
  const hold = prefersReducedMotion() ? 3000 : OVERLAY_MS;
  overlayTimer = setTimeout(() => {
    if (id !== celebrationId) return;
    overlay.hidden = true;
    shownGenotype = newGenotype;
    pendingGenotype = null;
    renderGenotype($('#genotype'), newGenotype);
  }, hold);
}

async function poll() {
  try {
    const s = await api('GET', '/api/booth/' + encodeURIComponent(boothId) + '/state'
      + (screenToken ? '?screen=' + encodeURIComponent(screenToken) : ''));
    $('#offline').hidden = true;
    $('#booth-error').hidden = true;
    showState(s);
  } catch (e) {
    if (e.status === 404) {
      const box = $('#booth-error');
      box.textContent = 'Nie ma takiego stoiska: „' + boothId + '”.';
      box.hidden = false;
    } else {
      $('#offline').hidden = false;
    }
  }
  setTimeout(poll, POLL_MS);
}

function tickTimer() {
  if (!qrPath) return;
  const left = Math.max(0, (qrChangeAt - Date.now()) / 1000);
  $('#qr-timer-fill').style.width = Math.min(100, (left / QR_PERIOD_S) * 100) + '%';
  $('#qr-timer-text').textContent = 'Kod QR zmieni się za ' + Math.ceil(left) + ' s';
}
setInterval(tickTimer, 500);

poll();
