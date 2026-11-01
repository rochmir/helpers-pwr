// Certyfikaty i grafiki rysowane na canvasie w tozsamosci DKMS / Helpers' Generation.
// Wszystkie grafiki (gracz 10/10, dawca, dawca faktyczny, wynik gry, social) korzystaja z jednej ramki drawFrame
// (tlo z lagodnym wzorem, naglowek z logotypami, pasek partnerow, czerwony pas) i jednego ukladu tresci:
// lista blokow (tytul, akcent, tekst...) ustawiana pionowo na srodku obszaru miedzy naglowkiem a paskiem.
// Prywatnosc: imiona/ksywki sa uzywane wylacznie w canvasie, nigdy nie trafiaja na serwer.

import { h, icon, facultyLabel, formatWarsaw, getConfig } from './common.js';

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


// ---------- partnerzy ----------

/** Pobiera liste partnerow (/api/partners) i ich obrazy. Blad lub brak = pusta lista (pasek sie nie rysuje). */
async function loadPartners() {
  let list = [];
  try {
    const res = await fetch('/api/partners', { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
    if (res.ok) list = await res.json();
  } catch (e) { list = []; }
  if (!Array.isArray(list)) return [];
  const loaded = await Promise.all(list.map(async (p) => {
    try {
      const img = new Image();
      img.src = p.url;
      await img.decode();
      const w = img.naturalWidth || img.width;
      const hh = img.naturalHeight || img.height;
      if (!w || !hh) return null;
      return { img, ratio: w / hh };
    } catch (e) { return null; }
  }));
  return loaded.filter(Boolean);
}

// ---------- ramka wspolna dla wszystkich grafik ----------

const SHAPE_COLORS = ['#2c5a82', '#e2001a', '#30783e', '#ffb500']; // jak w grze (style.css: --shape-0..3)

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

/** Lagodny wzor tla: kafel z ksztaltami gry powtarzany na calym obrazie, alfa 0,06 (nie obniza czytelnosci tekstu). */
function drawPattern(ctx, W, H) {
  const step = 132;
  ctx.save();
  ctx.globalAlpha = 0.06;
  for (let row = 0, y = 40; y < H + step; row++, y += step) {
    for (let col = 0, x = (row % 2) * (step / 2); x < W + step; col++, x += step) {
      drawShape(ctx, (col + row * 2) % 4, x, y, 24);
    }
  }
  ctx.restore();
}

/** Naglowek: czerwony akcent + logotypy DKMS (lewo), PWr (srodek) i Samorzadu Studenckiego (prawo). Zwraca y pod naglowkiem. */
function drawHeader(ctx, W, logos) {
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, W, HEADER_H + 2);
  ctx.fillStyle = C.red;
  ctx.fillRect(0, 0, W, 22);
  drawLogo(ctx, logos.dkms, 64, 76, 72, 'left');
  const dkmsEnd = 64 + (logos.dkms ? 72 * logos.dkms.ratio : 0);
  const ssStart = W - 64 - (logos.ss ? 64 * logos.ss.ratio : 0);
  if (logos.ss) drawLogo(ctx, logos.ss, W - 64, 80, 64, 'right');
  if (logos.pwr) drawLogo(ctx, logos.pwr, (dkmsEnd + ssStart) / 2 - (64 * logos.pwr.ratio) / 2, 80, 64);
  ctx.fillStyle = C.light;
  ctx.fillRect(64, HEADER_H, W - 128, 2);
  return HEADER_H + 2;
}

const HEADER_H = 190;

/** Wordmark tekstowy "Helpers' Generation" (gdy brak pliku logo). Wysrodkowany w x. */
function drawWordmark(ctx, x, y, px) {
  const a = "Helpers' ";
  const b = 'Generation';
  ctx.save();
  ctx.textAlign = 'left';
  ctx.fillStyle = '#ffffff';
  ctx.font = '600 ' + px + 'px ' + FONT_FAMILY;
  const wa = ctx.measureText(a).width;
  ctx.font = '800 ' + px + 'px ' + FONT_FAMILY;
  const wb = ctx.measureText(b).width;
  const x0 = x - (wa + wb) / 2;
  ctx.font = '600 ' + px + 'px ' + FONT_FAMILY;
  ctx.fillText(a, x0, y);
  ctx.font = '800 ' + px + 'px ' + FONT_FAMILY;
  ctx.fillText(b, x0 + wa, y);
  ctx.restore();
}

/** Dolny czerwony pas z bialym logo Helpers' Generation i podpisem. Zwraca y gornej krawedzi pasa. */
function drawFooterBand(ctx, W, H, bandH, logos, dateText) {
  const top = H - bandH;
  ctx.fillStyle = C.red;
  ctx.fillRect(0, top, W, bandH);
  const px = Math.round(bandH * 0.26);
  if (logos && logos.hgWhite) {
    const logoH = Math.round(bandH * 0.35);
    drawLogo(ctx, logos.hgWhite, W / 2 - (logoH * logos.hgWhite.ratio) / 2, top + Math.round(bandH * 0.1), logoH);
  } else {
    drawWordmark(ctx, W / 2, top + bandH * 0.4 + px * 0.35, px);
  }
  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'center';
  ctx.font = '400 ' + Math.round(px * 0.55) + 'px ' + FONT_FAMILY;
  ctx.fillText('Politechnika Wrocławska' + (dateText ? '  ·  ' + dateText : ''), W / 2, top + bandH * 0.4 + px * 0.35 + px * 0.95);
  return top;
}

/** Pasek partnerow nad czerwonym pasem; loga skalowane tak, by zmiescily sie w szerokosci i wysokosci. Zwraca jego wysokosc. */
function partnersBarHeight(partners, H) {
  if (!partners.length) return 0;
  return H < 1200 ? 120 : 150;
}

function drawPartnersBar(ctx, W, bottom, barH, partners) {
  const top = bottom - barH;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, top, W, barH);
  ctx.fillStyle = C.light;
  ctx.fillRect(64, top, W - 128, 2);
  ctx.fillStyle = C.grey;
  ctx.textAlign = 'center';
  ctx.font = '600 ' + Math.round(barH * 0.15) + 'px ' + FONT_FAMILY;
  ctx.fillText('Partnerzy', W / 2, top + barH * 0.27);
  const gap = 48;
  const maxW = W - 160;
  const maxH = Math.round(barH * 0.46);
  let k = 1;
  const widthAt = (kk) => partners.reduce((a, p) => a + maxH * kk * p.ratio, 0) + gap * kk * (partners.length - 1);
  if (widthAt(1) > maxW) k = maxW / widthAt(1);
  let x = (W - widthAt(k)) / 2;
  const y0 = top + barH * 0.4;
  const boxH = barH * 0.52;
  for (const p of partners) {
    let hh = maxH * k;
    let ww = hh * p.ratio;
    if (hh > boxH) { hh = boxH; ww = hh * p.ratio; }
    ctx.drawImage(p.img, x, y0 + (boxH - hh) / 2, ww, hh);
    x += maxH * k * p.ratio + gap * k;
  }
}

/** Rysuje cala ramke (tlo, wzor, naglowek, pasek partnerow, czerwony pas); zwraca obszar tresci {top, bottom}. */
export function drawFrame(canvas, { logos, partners = [], bandH = 230, dateText = '' }) {
  const W = canvas.width;
  const H = canvas.height;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, W, H);
  drawPattern(ctx, W, H);
  const top = drawHeader(ctx, W, logos);
  const bandTop = drawFooterBand(ctx, W, H, bandH, logos, dateText);
  const barH = partnersBarHeight(partners, H);
  if (barH) drawPartnersBar(ctx, W, bandTop, barH, partners);
  ctx.fillStyle = C.black;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  return { top, bottom: bandTop - barH };
}

// ---------- uklad tresci (bloki) ----------

/** Rzad ksztaltow genotypu w bialych komorkach z szara ramka, wysrodkowany; top = gorna krawedz. */
function drawGenotypeRow(ctx, genotype, W, top, maxW, cellMax) {
  const n = genotype.length;
  const gap = 10;
  const cell = Math.min(cellMax, Math.floor((maxW - gap * (n - 1)) / n));
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
  return cell;
}

const LINE_H = 1.25;

/**
 * Ustawia bloki pionowo (jedna skala s) od startY. Zwraca y konca. dry=true tylko mierzy.
 * Bloki: {t:'title'|'hero'|'text'|'label'|'fit'|'genotype'|'rule'|'gap', ...}; mt = odstep nad blokiem (px przy s=1).
 */
function layoutBlocks(ctx, W, blocks, s, startY, dry) {
  const maxW = W - 160;
  let y = startY;
  for (const b of blocks) {
    y += (b.mt || 0) * s;
    if (b.t === 'gap') continue;
    if (b.t === 'rule') {
      if (!dry) { ctx.fillStyle = C.red; ctx.fillRect(W / 2 - 60 * s, y, 120 * s, 8 * s); }
      y += 8 * s;
      continue;
    }
    if (b.t === 'genotype') {
      const cellMax = Math.round(84 * s);
      const n = b.value.length;
      const cell = Math.min(cellMax, Math.floor((maxW - 10 * (n - 1)) / n));
      if (!dry) drawGenotypeRow(ctx, b.value, W, y, maxW, cellMax);
      y += cell;
      continue;
    }
    const weight = b.weight || (b.t === 'title' || b.t === 'hero' ? '800' : b.t === 'label' ? '600' : '400');
    let px = Math.round((b.size || 40) * s);
    const wMax = b.narrow ? maxW - 80 : maxW;
    if (b.t === 'hero' || b.t === 'fit' || b.t === 'title') {
      // pojedyncza linia, o ile sie da: zmniejsz font do minimum (28 px), potem zawijaj
      const floor = Math.max(28, Math.round(px * 0.55));
      while (px > floor) {
        ctx.font = weight + ' ' + px + 'px ' + FONT_FAMILY;
        if (ctx.measureText(b.text).width <= wMax) break;
        px -= 2;
      }
    }
    ctx.font = weight + ' ' + px + 'px ' + FONT_FAMILY;
    const lh = Math.round(px * LINE_H);
    const lines = wrapLines(ctx, b.text, wMax);
    if (!dry) {
      ctx.fillStyle = b.color || (b.t === 'label' ? C.grey : b.t === 'text' ? C.dark : C.black);
      lines.forEach((l, i) => ctx.fillText(l, W / 2, y + i * lh + (lh - px) / 2 + px * 0.8));
    }
    y += lines.length * lh;
  }
  return y;
}

/** Rysuje grafike: ramka + bloki wysrodkowane w pionie (skala maleje, az tresc sie zmiesci). */
async function drawGraphic(canvas, blocks, { logos, partners, bandH = 230, dateText = '', sMax = 1 }) {
  const ctx = canvas.getContext('2d');
  const area = drawFrame(canvas, { logos, partners, bandH, dateText });
  const avail = area.bottom - area.top;
  const margin = 56;
  let s = sMax;
  let used = layoutBlocks(ctx, canvas.width, blocks, s, 0, true);
  while (used > avail - 2 * margin && s > 0.4) {
    s = Math.max(0.4, s - 0.03);
    used = layoutBlocks(ctx, canvas.width, blocks, s, 0, true);
  }
  const startY = area.top + Math.max(margin, (avail - used) / 2);
  ctx.textAlign = 'center';
  layoutBlocks(ctx, canvas.width, blocks, s, startY, false);
  return { top: area.top, bottom: area.bottom, startY, endY: startY + used, scale: s };
}

async function prepare() {
  await ensureFonts();
  const [logos, partners] = await Promise.all([loadLogos(), loadPartners()]);
  return { logos, partners };
}

const DATE_LONG = { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/Warsaw' };
function dateLong(d) {
  const dd = d ? new Date(d) : new Date();
  return (Number.isNaN(dd.getTime()) ? new Date() : dd).toLocaleDateString('pl-PL', DATE_LONG);
}
const fmtNum = (n) => String(n).replace('.', ',');

// ---------- certyfikat gracza 10/10 ----------

/** Dane z serwera: genotype, wonAt (ISO UTC), token, boothName. nick tylko do canvasu. */
export async function renderPlayerCert({ nick, genotype, wonAt, token, boothName } = {}) {
  const ctxs = await prepare();
  const canvas = makeCanvas(1080, 1920);
  const when = formatWarsaw(wonAt);
  const name = (nick || '').trim();
  const blocks = [
    { t: 'title', text: 'Genotyp 10/10!', size: 124 },
    { t: 'rule', mt: 30 },
    { t: 'label', text: 'Gratulacje', size: 46, mt: 40, color: C.black },
  ];
  if (name) blocks.push({ t: 'hero', text: name, size: 92, color: C.red, mt: 8 });
  if (token) {
    blocks.push({ t: 'label', text: 'Token Losu', size: 34, mt: 44 });
    blocks.push({ t: 'hero', text: token, size: 92, color: C.red, mt: 4, weight: '800' });
  }
  if (genotype) {
    blocks.push({ t: 'label', text: 'Twój wzór', size: 34, mt: 40 });
    blocks.push({ t: 'genotype', value: genotype, mt: 14 });
  }
  if (when) blocks.push({ t: 'text', text: 'Data i godzina: ' + when, size: 38, weight: '600', color: C.black, mt: 36 });
  if (boothName) blocks.push({ t: 'text', text: 'Stanowisko: ' + boothName, size: 38, mt: 4 });
  blocks.push({ t: 'text', text: 'Udało Ci się zostać wirtualnym bliźniakiem genetycznym w symulatorze HLA. W symulatorze 1 do 300. W rzeczywistości szansa na bliźniaka genetycznego to około 1 do 1 000 000.', size: 36, narrow: true, mt: 44 });
  blocks.push({ t: 'text', text: 'Prawdziwego bliźniaka genetycznego możesz uratować w rzeczywistości. Zarejestruj się jako potencjalny Dawca szpiku.', size: 36, narrow: true, mt: 20 });
  await drawGraphic(canvas, blocks, { ...ctxs, dateText: when ? '' : dateLong() });
  return canvas;
}

// ---------- certyfikat dawcy ----------

export async function renderDonorCert({ name, facultyName, kind } = {}) {
  const ctxs = await prepare();
  const canvas = makeCanvas(1080, 1920);
  const nm = (name || '').trim();
  const actual = kind === 'actual';
  const blocks = [
    { t: 'title', text: actual ? 'Certyfikat Dawcy Szpiku' : 'Certyfikat Potencjalnego Dawcy Szpiku', size: 92 },
    { t: 'rule', mt: 30 },
  ];
  if (nm) {
    blocks.push({ t: 'label', text: 'Dla', size: 40, mt: 44 });
    blocks.push({ t: 'hero', text: nm, size: 100, color: C.red, mt: 6 });
  }
  if (facultyName) blocks.push({ t: 'text', text: facultyName, size: 44, weight: '600', mt: 40 });
  blocks.push({ t: 'text', size: 38, narrow: true, mt: 56, text: actual
    ? "Jesteś Dawcą faktycznym. Dziękujemy za Twój dar i za udział w akcji Helpers' Generation na Politechnice Wrocławskiej."
    : "Dziękujemy, że dołączasz do grona potencjalnych Dawców szpiku podczas Helpers' Generation 2026 na Politechnice Wrocławskiej." });
  await drawGraphic(canvas, blocks, { ...ctxs, dateText: dateLong() });
  return canvas;
}

// ---------- wynik gry ----------

/** Grafika 9:16 z najlepszym wynikiem gracza. nick tylko do canvasu; best 0..10; date = ISO lub Date. */
export async function renderResultCert({ nick, best, boothName, date } = {}) {
  const ctxs = await prepare();
  let host = location.host;
  try {
    const cfg = await getConfig();
    if (cfg && cfg.public_url) host = String(cfg.public_url).replace(/^https?:\/\//, '').replace(/\/+$/, '');
  } catch (e) { /* zostaje host strony */ }
  const canvas = makeCanvas(1080, 1920);
  const name = (nick || '').trim();
  const blocks = [
    { t: 'title', text: 'Mój wynik w HLA Match Maker', size: 84 },
    { t: 'rule', mt: 30 },
  ];
  if (name) blocks.push({ t: 'hero', text: name, size: 84, color: C.black, mt: 40 });
  blocks.push({ t: 'hero', text: Number.isFinite(best) ? best + '/10' : '-', size: 300, color: C.red, mt: 20 });
  blocks.push({ t: 'text', text: 'najlepszy wynik dnia', size: 44, weight: '600', color: C.black, mt: 0 });
  if (boothName) blocks.push({ t: 'text', text: 'Stanowisko: ' + boothName, size: 38, mt: 36 });
  blocks.push({ t: 'text', text: dateLong(date), size: 38, mt: 4 });
  blocks.push({ t: 'text', size: 38, narrow: true, mt: 56,
    text: 'Wzór stoiska należy do pacjenta czekającego na Dawcę. Sprawdź swoje parametry i zobacz, czy Ty jesteś jego bliźniakiem genetycznym.' });
  blocks.push({ t: 'fit', text: 'Sprawdź parametry: ' + host + '/graj', size: 46, weight: '800', color: C.red, mt: 36 });
  await drawGraphic(canvas, blocks, { ...ctxs, dateText: '' });
  return canvas;
}

// ---------- grafika social media ----------

export const SOCIAL_FORMATS = {
  '9:16': { width: 1080, height: 1920 },
  '4:5': { width: 1080, height: 1350 },
  '1:1': { width: 1080, height: 1080 },
};

function socialBlocks(sm) {
  const title = sm.scope === 'day' && sm.date ? dateLong(sm.date + 'T12:00:00') : 'Podsumowanie akcji';
  const blocks = [
    { t: 'title', text: title, size: 64 },
    { t: 'rule', mt: 24 },
    { t: 'hero', text: Number.isFinite(sm.registered) ? String(sm.registered) : 'Brak danych', size: 170, color: C.red, mt: 20 },
    { t: 'text', text: sm.scope === 'day' ? 'punktów w Pucharze tego dnia' : 'punktów w Pucharze Dawcy PWr', size: 38, weight: '600', color: C.dark, mt: 0 },
  ];
  if (sm.scope === 'day' && Number.isFinite(sm.registered_total)) {
    blocks.push({ t: 'text', text: 'łącznie w akcji: ' + sm.registered_total, size: 34, mt: 8 });
  }
  const cup = Array.isArray(sm.cup) ? sm.cup.slice(0, 3) : [];
  const podium = Array.isArray(sm.podium) ? sm.podium.slice(0, 3) : [];
  blocks.push({ t: 'text', text: cup.length ? 'Puchar Dawcy PWr' : 'Wydziały z największą liczbą punktów', size: 46, weight: '800', color: C.black, mt: 56 });
  if (cup.length) {
    cup.forEach((p, i) => {
      blocks.push({ t: 'fit', text: (p.rank || i + 1) + '. ' + (p.name ? facultyLabel(p) : p.code), size: 38, mt: i ? 18 : 16 });
      blocks.push({ t: 'text', text: 'WZ: ' + fmtNum(p.wz) + ' (punkty: ' + p.registered + ')', size: 32, color: C.grey, mt: 0 });
    });
  } else if (podium.length) {
    podium.forEach((p, i) => {
      blocks.push({ t: 'fit', text: (i + 1) + '. ' + (p.name ? facultyLabel(p) : p.code) + ': ' + p.count + ' pkt', size: 38, mt: i ? 12 : 16 });
    });
  } else {
    blocks.push({ t: 'text', text: 'Brak danych', size: 38, mt: 16 });
  }
  blocks.push({ t: 'text', text: 'Symulator HLA', size: 46, weight: '800', color: C.black, mt: 56 });
  const g = sm.game;
  if (g) {
    blocks.push({ t: 'text', text: 'Uczestników: ' + g.players + ', prób: ' + g.rolls, size: 38, mt: 14 });
    blocks.push({ t: 'text', text: 'Trafień 10/10: ' + g.matches, size: 38, mt: 4 });
  } else {
    blocks.push({ t: 'text', text: 'Brak danych', size: 38, mt: 14 });
  }
  return blocks;
}

export async function renderSocial(summary, format = '9:16') {
  const ctxs = await prepare();
  const f = SOCIAL_FORMATS[format] || SOCIAL_FORMATS['9:16'];
  const canvas = makeCanvas(f.width, f.height);
  await drawGraphic(canvas, socialBlocks(summary || {}), { ...ctxs, bandH: f.height < 1200 ? 150 : 200, dateText: '' });
  return canvas;
}

// ---------- pobieranie i udostepnianie ----------

function canvasBlob(canvas) {
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/png'));
}

/** Pokazuje PNG jako <img> (przytrzymanie na telefonie), przycisk Pobierz i (gdy przegladarka umie) Udostepnij. */
export async function showDownload(canvas, container, filename = 'certyfikat.png') {
  const dataUrl = canvas.toDataURL('image/png');
  const blob = await canvasBlob(canvas); // gotowy przed kliknieciem, bo navigator.share wymaga gestu uzytkownika
  let file = null;
  try {
    if (blob && typeof File === 'function') file = new File([blob], filename, { type: 'image/png' });
  } catch (e) { file = null; }
  const canShare = !!(file && navigator.share && navigator.canShare && navigator.canShare({ files: [file] }));
  const row = h('div', { class: 'share-row' },
    h('a', { class: 'btn btn-primary download-btn', href: dataUrl, download: filename }, icon('ti-download'), 'Pobierz (PNG)'));
  if (canShare) {
    const btn = h('button', { class: 'btn btn-inverted share-btn', type: 'button' }, icon('ti-share'), 'Udostępnij');
    btn.addEventListener('click', async () => {
      try {
        await navigator.share({ files: [file] });
      } catch (e) {
        if (!e || e.name !== 'AbortError') btn.textContent = 'Nie udało się udostępnić, użyj Pobierz';
      }
    });
    row.append(btn);
  }
  container.textContent = '';
  container.append(
    h('img', { class: 'download-img', src: dataUrl, alt: 'Wygenerowany obraz do pobrania' }),
    row,
    h('p', { class: 'download-hint' }, 'Kliknij przycisk Pobierz lub przytrzymaj palcem na obrazku, aby zapisać go w galerii'),
  );
  if (canShare) {
    container.append(h('p', { class: 'download-hint' }, 'Udostępnij otwiera menu telefonu, wybierz np. Instagram lub Facebook. Obraz nie zapisuje się w galerii.'));
  }
  container.hidden = false;
}
