// Certyfikaty i grafika social media rysowane na canvasie w tozsamosci DKMS / Helpers' Generation:
// biale tlo, czerwony (#E2001A) akcent, logotypy DKMS i PWr (SVG z /static/brand/), font Inter (lokalny).
// Funkcje drawPlayerCert / drawDonorCert / drawSocial mozna podmienic; reszta (fonty, canvas, PNG, <img>) zostaje.
// Prywatnosc: imiona/ksywki sa uzywane wylacznie w canvasie, nigdy nie trafiaja na serwer.
// Na certyfikacie gracza widac wzor i czas trafienia (dane z serwera, anonimowe) - to dowod w losowaniu finalowym.

import { h, icon, facultyLabel, formatWarsaw } from './common.js';

export const FONT_FAMILY = "'Inter', system-ui, sans-serif";

const C = { red: '#E2001A', black: '#000000', dark: '#282832', grey: '#666666', light: '#D9D9D9', bg: '#F4F4F9', pink: '#F9CCD1' };
const FONT_DIR = '/static/fonts/';
const FONT_SUBSETS = {
  'latin-ext': 'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF',
  latin: 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD',
};
const FONT_WEIGHTS = ['400', '600', '800'];

let fontsPromise = null;
/** Laduje Inter (400/600/800, latin + latin-ext) z /static/fonts/ przez FontFace; po cichu spada na system-ui. */
export function ensureFonts() {
  if (!fontsPromise) {
    fontsPromise = (async () => {
      const jobs = [];
      for (const [subset, unicodeRange] of Object.entries(FONT_SUBSETS)) {
        for (const weight of FONT_WEIGHTS) {
          jobs.push((async () => {
            const face = new FontFace('Inter', 'url(' + FONT_DIR + 'inter-' + subset + '-' + weight + '-normal.woff2)',
              { weight, style: 'normal', unicodeRange });
            await face.load();
            document.fonts.add(face);
          })());
        }
      }
      await Promise.allSettled(jobs); // brak pliku = font systemowy
      try { await document.fonts.ready; } catch (e) { /* ignoruj */ }
    })();
  }
  return fontsPromise;
}

// ---------- logotypy ----------

const LOGO_FILES = {
  dkms: { url: '/static/brand/dkms-logo.svg', ratio: 132 / 40 },
  pwr: { url: '/static/brand/pwr-logo.svg', ratio: 340 / 73 },
  pwrWhite: { url: '/static/brand/pwr-logo-white.svg', ratio: 340 / 73 },
  hg: { url: '/static/brand/helpers-generation-logo.svg', ratio: 777.54 / 264.69 },
  hgWhite: { url: '/static/brand/helpers-generation-logo-white.svg', ratio: 777.54 / 264.69 }, // na czerwonym pasie
  ss: { url: '/static/brand/samorzad-studencki.svg', ratio: 221.3 / 60.9 },
};
const logoCache = {};

function loadLogo(key) {
  if (!logoCache[key]) {
    logoCache[key] = (async () => {
      try {
        const img = new Image();
        img.src = LOGO_FILES[key].url;
        await img.decode();
        return { img, ratio: LOGO_FILES[key].ratio };
      } catch (e) { return null; } // brak logo = pomijamy
    })();
  }
  return logoCache[key];
}

async function loadLogos() {
  const [dkms, pwr, pwrWhite, hg, hgWhite, ss] = await Promise.all(
    ['dkms', 'pwr', 'pwrWhite', 'hg', 'hgWhite', 'ss'].map(loadLogo),
  );
  return { dkms, pwr, pwrWhite, hg, hgWhite, ss };
}

function drawLogo(ctx, logo, x, y, height, align = 'left') {
  if (!logo) return;
  const w = height * logo.ratio;
  ctx.drawImage(logo.img, align === 'right' ? x - w : x, y, w, height);
}

// ---------- pomocnicze ----------

function makeCanvas(w, h_) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h_;
  return c;
}

/** Dzieli tekst na linie miescace sie w maxWidth (lamie tez bardzo dlugie slowa). */
export function wrapLines(ctx, text, maxWidth) {
  const lines = [];
  for (const para of String(text).split('\n')) {
    let line = '';
    for (const word of para.split(/\s+/).filter(Boolean)) {
      let w = word;
      while (ctx.measureText(w).width > maxWidth && w.length > 1) {
        let cut = w.length - 1;
        while (cut > 1 && ctx.measureText(w.slice(0, cut)).width > maxWidth) cut--;
        if (line) { lines.push(line); line = ''; }
        lines.push(w.slice(0, cut));
        w = w.slice(cut);
      }
      const test = line ? line + ' ' + w : w;
      if (line && ctx.measureText(test).width > maxWidth) { lines.push(line); line = w; } else line = test;
    }
    lines.push(line);
  }
  return lines;
}

/** Rysuje zawiniety tekst (wg ctx.textAlign); zwraca y pod ostatnia linia. dry=true tylko liczy. */
export function drawWrapped(ctx, text, x, y, maxWidth, lineHeight, dry = false) {
  const lines = wrapLines(ctx, text, maxWidth);
  if (!dry) lines.forEach((l, i) => ctx.fillText(l, x, y + i * lineHeight));
  return y + lines.length * lineHeight;
}

/** Zmniejsza font, az tekst zmiesci sie w jednej linii (min 28px). Zwraca uzyty rozmiar. */
function fitFont(ctx, text, maxWidth, startPx, weight = '800') {
  let px = startPx;
  do {
    ctx.font = weight + ' ' + px + 'px ' + FONT_FAMILY;
    px -= 4;
  } while (px > 28 && ctx.measureText(text).width > maxWidth);
  return px + 4;
}

function setup(canvas) {
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = C.black;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  return ctx;
}

// Kolory ksztaltow jak w grze (style.css: --shape-0..3).
const SHAPE_COLORS = ['#2c5a82', '#e2001a', '#30783e', '#ffb500'];

/** Wypelniony ksztalt genotypu (0 trojkat, 1 kolo, 2 kwadrat, 3 gwiazdka) wpisany w kolo o promieniu r. */
function drawShape(ctx, idx, cx, cy, r) {
  ctx.fillStyle = SHAPE_COLORS[idx];
  ctx.beginPath();
  if (idx === 0) {
    ctx.moveTo(cx, cy - r);
    ctx.lineTo(cx + r * 0.95, cy + r * 0.8);
    ctx.lineTo(cx - r * 0.95, cy + r * 0.8);
    ctx.closePath();
  } else if (idx === 1) {
    ctx.arc(cx, cy, r * 0.92, 0, Math.PI * 2);
  } else if (idx === 2) {
    const s = r * 0.85;
    ctx.rect(cx - s, cy - s, s * 2, s * 2);
  } else {
    for (let i = 0; i < 10; i++) {
      const rad = i % 2 === 0 ? r : r * 0.45;
      const a = -Math.PI / 2 + (i * Math.PI) / 5;
      const px = cx + Math.cos(a) * rad;
      const py = cy + Math.sin(a) * rad;
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();
  }
  ctx.fill();
}

/** Rzad ksztaltow genotypu w bialych komorkach z szara ramka, wysrodkowany; zwraca y pod rzedem. */
function drawGenotypeRow(ctx, genotype, W, top, maxW) {
  const n = genotype.length;
  const gap = 10;
  const cell = Math.min(84, Math.floor((maxW - gap * (n - 1)) / n));
  const x0 = (W - (n * cell + (n - 1) * gap)) / 2;
  for (let i = 0; i < n; i++) {
    const x = x0 + i * (cell + gap);
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = C.light;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.roundRect(x, top, cell, cell, 12);
    ctx.fill();
    ctx.stroke();
    const idx = Number(genotype[i]);
    if (idx >= 0 && idx < SHAPE_COLORS.length) drawShape(ctx, idx, x + cell / 2, top + cell / 2, cell * 0.32);
  }
  return top + cell;
}

function todayPl() {
  return new Date().toLocaleDateString('pl-PL', { day: 'numeric', month: 'long', year: 'numeric' });
}

const HEADER_H = 190;

/** Gorny pas: czerwony akcent + logotypy DKMS (lewo), Samorzadu Studenckiego (srodek) i PWr (prawo). Zwraca y pod naglowkiem. */
function drawHeader(ctx, W, logos) {
  ctx.fillStyle = C.red;
  ctx.fillRect(0, 0, W, 22);
  drawLogo(ctx, logos.dkms, 64, 76, 72, 'left');
  // kolejnosc: DKMS, PWr, samorzad (HG na dole, w czerwonym pasku)
  // W=1080: DKMS x=64..302, PWr x=393..691 (srodek luki), samorzad x=783..1016 - luki ok. 92px
  const dkmsEnd = 64 + (logos.dkms ? 72 * logos.dkms.ratio : 0);
  const ssStart = W - 64 - (logos.ss ? 64 * logos.ss.ratio : 0);
  if (logos.ss) drawLogo(ctx, logos.ss, W - 64, 80, 64, 'right');
  if (logos.pwr) drawLogo(ctx, logos.pwr, (dkmsEnd + ssStart) / 2 - (64 * logos.pwr.ratio) / 2, 80, 64);
  ctx.fillStyle = C.light;
  ctx.fillRect(64, HEADER_H, W - 128, 2);
  return HEADER_H + 2;
}

/** Wordmark tekstowy "Helpers' Generation" (bez grafiki). Wysrodkowany w x. */
function drawWordmark(ctx, x, y, px, onRed = false) {
  const a = "Helpers' ";
  const b = 'Generation';
  ctx.save();
  ctx.textAlign = 'left';
  ctx.font = '600 ' + px + 'px ' + FONT_FAMILY;
  const wa = ctx.measureText(a).width;
  ctx.font = '800 ' + px + 'px ' + FONT_FAMILY;
  const wb = ctx.measureText(b).width;
  const x0 = x - (wa + wb) / 2;
  ctx.fillStyle = onRed ? '#ffffff' : C.black;
  ctx.font = '600 ' + px + 'px ' + FONT_FAMILY;
  ctx.fillText(a, x0, y);
  ctx.fillStyle = onRed ? '#ffffff' : C.red;
  ctx.font = '800 ' + px + 'px ' + FONT_FAMILY;
  ctx.fillText(b, x0 + wa, y);
  ctx.restore();
}

/** Dolny czerwony pas z bialym logo Helpers' Generation (gdy brak pliku, wordmark tekstowy); opcjonalnie data
 *  (withDate: true = dzisiejsza, false = brak, tekst = podana). 
 *  Zwraca y gornej krawedzi pasa. */
function drawFooterBand(ctx, W, H, bandH, logos, withDate = true) {
  const top = H - bandH;
  ctx.fillStyle = C.red;
  ctx.fillRect(0, top, W, bandH);
  const px = Math.round(bandH * 0.26);
  if (logos && logos.hgWhite) { // biale logo na czerwonym pasie
    const logoH = Math.round(bandH * 0.35);
    drawLogo(ctx, logos.hgWhite, W / 2 - (logoH * logos.hgWhite.ratio) / 2, top + Math.round(bandH * 0.1), logoH);
  } else {
    drawWordmark(ctx, W / 2, top + bandH * 0.4 + px * 0.35, px, true);
  }
  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'center';
  ctx.font = '400 ' + Math.round(px * 0.55) + 'px ' + FONT_FAMILY;
  ctx.fillText('Politechnika Wrocławska' + (withDate ? '  ·  ' + (typeof withDate === 'string' ? withDate : todayPl()) : ''), W / 2, top + bandH * 0.4 + px * 0.35 + px * 0.95);
  return top;
}

/** Krotka czerwona linia pod tytulem. */
function accentRule(ctx, x, y) {
  ctx.fillStyle = C.red;
  ctx.fillRect(x - 60, y, 120, 8);
}

// ---------- certyfikat gracza ----------

/** genotype/wonAt (z serwera) = wzor i czas trafienia; bez nich (stara sesja) certyfikat jest bez tego bloku. */
function drawPlayerCert(canvas, nick, genotype, wonAt, logos) {
  const W = canvas.width;
  const H = canvas.height;
  const ctx = setup(canvas);
  const maxW = W - 160;
  drawHeader(ctx, W, logos); // konczy sie na y=192
  const when = formatWarsaw(wonAt);
  // data w pasie tylko gdy brak czasu trafienia (inaczej bylaby powtorzona)
  const bandTop = drawFooterBand(ctx, W, H, 230, logos, !when); // pas od y=H-230=1690

  const top = HEADER_H + 2;
  const gap = 70; // minimalny odstep tresci od naglowka i od pasa

  /** Tresc certyfikatu od y=startY (gorna krawedz); dry=true tylko mierzy. Zwraca y konca tresci. */
  const body = (startY, dry) => {
    let y = startY;
    const tpx = fitFont(ctx, 'Genotyp 10/10!', maxW, 130);
    ctx.fillStyle = C.red;
    if (!dry) ctx.fillText('Genotyp 10/10!', W / 2, y + tpx * 0.78);
    y += tpx * 0.78 + 64;
    if (!dry) accentRule(ctx, W / 2, y);
    y += 8 + 48;
    ctx.fillStyle = C.black;
    ctx.font = '600 48px ' + FONT_FAMILY;
    y = drawWrapped(ctx, 'Gratulacje', W / 2, y + 36, maxW, 60, dry) - 24;
    if (nick) {
      const px = fitFont(ctx, nick, maxW, 96);
      ctx.font = '800 ' + px + 'px ' + FONT_FAMILY;
      y = drawWrapped(ctx, nick, W / 2, y + 16 + px * 0.8, maxW, px * 1.2, dry) - px * 0.9;
    }
    if (genotype) {
      y += 36;
      ctx.fillStyle = C.grey;
      ctx.font = '600 34px ' + FONT_FAMILY;
      y = drawWrapped(ctx, 'Twój wzór', W / 2, y + 28, maxW, 44, dry) - 16;
      if (dry) y += 12 + Math.min(84, Math.floor((maxW - 10 * (genotype.length - 1)) / genotype.length));
      else y = drawGenotypeRow(ctx, genotype, W, y + 12, maxW);
      if (when) {
        ctx.fillStyle = C.black;
        ctx.font = '600 38px ' + FONT_FAMILY;
        y = drawWrapped(ctx, 'Wylosowano: ' + when, W / 2, y + 56, maxW, 48, dry) - 12;
      }
    }
    y += 48;
    ctx.fillStyle = C.dark;
    ctx.font = '400 37px ' + FONT_FAMILY;
    y = drawWrapped(ctx,
      'Udało Ci się zostać wirtualnym bliźniakiem genetycznym w grze HLA. Szansa na to wynosiła 1 do 300.',
      W / 2, y + 30, maxW - 80, 54, dry) - 12;
    y = drawWrapped(ctx,
      'Prawdziwego bliźniaka genetycznego możesz uratować w rzeczywistości. Zarejestruj się jako potencjalny Dawca szpiku.',
      W / 2, y + 40, maxW - 80, 54, dry) - 12;
    return y;
  };

  // wysrodkowanie pionowe tresci miedzy naglowkiem a pasem (nie wyzej niz gap od naglowka)
  const used = body(0, true);
  const startY = top + Math.max(gap, (bandTop - top - used) / 2);
  body(startY, false);
  return bandTop;
}

/** nick: tylko do canvasu; genotype + wonAt: wzor i czas trafienia (ISO UTC z serwera). */
export async function renderPlayerCert(nick, genotype, wonAt) {
  await ensureFonts();
  const logos = await loadLogos();
  const canvas = makeCanvas(1080, 1920);
  drawPlayerCert(canvas, (nick || '').trim(), genotype || '', wonAt || '', logos);
  return canvas;
}

// ---------- certyfikat dawcy ----------

function drawDonorCert(canvas, { name, facultyName, kind }, logos) {
  const W = canvas.width;
  const H = canvas.height;
  const ctx = setup(canvas);
  const maxW = W - 160;
  drawHeader(ctx, W, logos);
  drawFooterBand(ctx, W, H, 230, logos);

  ctx.fillStyle = C.black;
  ctx.font = '800 84px ' + FONT_FAMILY;
  let y = drawWrapped(ctx, kind === 'actual' ? 'Certyfikat Dawcy Szpiku' : 'Certyfikat Potencjalnego Dawcy Szpiku', W / 2, 470, maxW, 104);
  accentRule(ctx, W / 2, y - 50);
  y += 50;
  if (name) {
    ctx.fillStyle = C.grey;
    ctx.font = '400 40px ' + FONT_FAMILY;
    ctx.fillText('Dla', W / 2, y + 40);
    const px = fitFont(ctx, name, maxW, 100);
    ctx.fillStyle = C.red;
    ctx.font = '800 ' + px + 'px ' + FONT_FAMILY;
    y = drawWrapped(ctx, name, W / 2, y + 140, maxW, px * 1.2);
  }
  if (facultyName) {
    ctx.fillStyle = C.dark;
    ctx.font = '600 44px ' + FONT_FAMILY;
    y = drawWrapped(ctx, facultyName, W / 2, y + 70, maxW, 60);
  }
  ctx.fillStyle = C.dark;
  ctx.font = '400 38px ' + FONT_FAMILY;
  const thanks = kind === 'actual'
    ? 'Jesteś Dawcą faktycznym. Dziękujemy za Twój dar i za udział w akcji Helpers\' Generation na Politechnice Wrocławskiej.'
    : 'Dziękujemy, że dołączasz do grona potencjalnych Dawców szpiku podczas Helpers\' Generation 2026 na Politechnice Wrocławskiej.';
  drawWrapped(ctx, thanks, W / 2, y + 100, maxW, 56);
}

export async function renderDonorCert({ name, facultyName, kind } = {}) {
  await ensureFonts();
  const logos = await loadLogos();
  const canvas = makeCanvas(1080, 1920);
  drawDonorCert(canvas, { name: (name || '').trim(), facultyName: facultyName || '', kind }, logos);
  return canvas;
}

// ---------- grafika social media ----------

export const SOCIAL_FORMATS = {
  '9:16': { width: 1080, height: 1920 },
  '4:5': { width: 1080, height: 1350 },
  '1:1': { width: 1080, height: 1080 },
};

/** Tresc grafiki; dry=true tylko mierzy wysokosc (do wysrodkowania pionowego). Zwraca y konca tresci. */
function socialBody(ctx, W, s, summary, startY, dry) {
  const maxW = W - 140;
  const put = (text, y) => { if (!dry) ctx.fillText(text, W / 2, y); };
  const sm = summary || {};
  const fs = (px) => Math.round(px * s);
  let y = startY;

  const title = sm.scope === 'day' && sm.date
    ? new Date(sm.date + 'T12:00:00').toLocaleDateString('pl-PL', { day: 'numeric', month: 'long', year: 'numeric' })
    : 'Podsumowanie akcji';
  ctx.fillStyle = C.black;
  ctx.font = '800 ' + fs(64) + 'px ' + FONT_FAMILY;
  y = drawWrapped(ctx, title, W / 2, y + fs(64), maxW, fs(76), dry);
  if (!dry) accentRule(ctx, W / 2, y - fs(20));

  ctx.fillStyle = C.red;
  ctx.font = '800 ' + fs(170) + 'px ' + FONT_FAMILY;
  y += fs(40) + fs(150);
  put(Number.isFinite(sm.registered) ? String(sm.registered) : 'Brak danych', y);
  ctx.fillStyle = C.dark;
  ctx.font = '600 ' + fs(38) + 'px ' + FONT_FAMILY;
  y += fs(62);
  put(sm.scope === 'day' ? 'zarejestrowanych tego dnia' : 'zarejestrowanych Dawców', y);
  if (sm.scope === 'day' && Number.isFinite(sm.registered_total)) {
    ctx.font = '400 ' + fs(34) + 'px ' + FONT_FAMILY;
    y += fs(50);
    put('łącznie w akcji: ' + sm.registered_total, y);
  }

  y += fs(90);
  ctx.fillStyle = C.black;
  ctx.font = '800 ' + fs(46) + 'px ' + FONT_FAMILY;
  put('Najlepsze wydziały', y);
  ctx.fillStyle = C.dark;
  ctx.font = '400 ' + fs(38) + 'px ' + FONT_FAMILY;
  const podium = Array.isArray(sm.podium) ? sm.podium.slice(0, 3) : [];
  if (!podium.length) {
    y += fs(62);
    put('Brak danych', y);
  }
  podium.forEach((p, i) => {
    const line = (i + 1) + '. ' + (p.name ? facultyLabel(p) : p.code) + ': ' + p.count;
    ctx.font = '400 ' + fitFont(ctx, line, maxW, fs(38), '400') + 'px ' + FONT_FAMILY; // dluga nazwa wydzialu: mniejszy font zamiast zawijania
    y = drawWrapped(ctx, line, W / 2, y + fs(62), maxW, fs(50), dry) - fs(50); // y = baza ostatniej linii
  });

  y += fs(90);
  ctx.fillStyle = C.black;
  ctx.font = '800 ' + fs(46) + 'px ' + FONT_FAMILY;
  put('Gra HLA', y);
  ctx.fillStyle = C.dark;
  ctx.font = '400 ' + fs(38) + 'px ' + FONT_FAMILY;
  const g = sm.game;
  if (g) {
    put('Graczy: ' + g.players + '   Losowań: ' + g.rolls, y + fs(62));
    put('Trafień 10/10: ' + g.matches, y + fs(116));
    y += fs(116);
  } else {
    put('Brak danych', y + fs(62));
    y += fs(62);
  }
  return y;
}

function drawSocial(canvas, summary, logos) {
  const W = canvas.width;
  const H = canvas.height;
  const ctx = setup(canvas);
  const top = drawHeader(ctx, W, logos);
  const bandH = H < 1200 ? 150 : 200;
  drawFooterBand(ctx, W, H, bandH, logos, false);
  const avail = H - top - bandH;
  const margin = 50; // min. odstep tresci od naglowka i od pasa
  let s = Math.max(0.5, Math.min(1.1, avail / 1000));
  ctx.textAlign = 'center';
  let used = socialBody(ctx, W, s, summary, 0, true);
  while (used > avail - 2 * margin && s > 0.5) { // tresc za wysoka (np. 1:1): zmniejsz skale
    s = Math.max(0.5, s - 0.03);
    used = socialBody(ctx, W, s, summary, 0, true);
  }
  const startY = top + Math.max(margin, (avail - used) / 2) - 10;
  socialBody(ctx, W, s, summary, startY, false);
}

export async function renderSocial(summary, format = '9:16') {
  await ensureFonts();
  const logos = await loadLogos();
  const f = SOCIAL_FORMATS[format] || SOCIAL_FORMATS['9:16'];
  const canvas = makeCanvas(f.width, f.height);
  drawSocial(canvas, summary, logos);
  return canvas;
}

// ---------- pobieranie ----------

/** Pokazuje PNG jako <img> (przytrzymanie na telefonie) + przycisk Pobierz. */
export function showDownload(canvas, container, filename = 'certyfikat.png') {
  const dataUrl = canvas.toDataURL('image/png');
  container.textContent = '';
  container.append(
    h('img', { class: 'download-img', src: dataUrl, alt: 'Wygenerowany obraz do pobrania' }),
    h('a', { class: 'btn btn-primary download-btn', href: dataUrl, download: filename }, icon('ti-download'), 'Pobierz (PNG)'),
    h('p', { class: 'download-hint' }, 'Kliknij przycisk Pobierz lub przytrzymaj palcem na obrazku, aby zapisać go w galerii'),
  );
  container.hidden = false;
}
