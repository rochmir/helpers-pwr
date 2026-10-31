// Pseudonimowe identyfikatory urzadzenia. Liczone w przegladarce (SHA-256), na serwer ida tylko skroty.
// base: sygnaly wspolne dla przegladarek tego samego urzadzenia (bez canvasa, WebGL, audio, jezyka, pamieci).
// ext: base + sygnaly rozrozniajace egzemplarze tego samego modelu. Zadnych pikseli canvas ani audio.
// Surowe wartosci nie opuszczaja przegladarki. Sygnaly nie zaleza od czasu, rozmiaru okna, orientacji,
// stanu sieci ani motywu, a listy sa sortowane, zeby kolejne wejscia dawaly ten sam wynik.

/** Rodzina systemu (+ major iOS) z user agenta; pomija wersje i nazwe przegladarki. */
function osSignal() {
  const ua = navigator.userAgent || '';
  const ios = /(iPhone|iPad|iPod)/.exec(ua);
  if (ios) {
    const v = /OS (\d+)[_.]/.exec(ua);
    return 'ios' + (v ? v[1] : '');
  }
  // iPadOS udaje Maca, ale ma ekran dotykowy
  if (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) return 'ipados';
  if (/Android/.test(ua)) return 'android';
  if (/Windows/.test(ua)) return 'windows';
  if (/Mac OS X|Macintosh/.test(ua)) return 'mac';
  if (/CrOS/.test(ua)) return 'cros';
  if (/Linux/.test(ua)) return 'linux';
  return 'other';
}

function timeZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return ''; }
}

/** True, gdy przegladarka potrafi policzyc skrot (crypto.subtle wymaga bezpiecznego kontekstu, czyli HTTPS). */
export function deviceHashSupported() {
  return !!(window.crypto && window.crypto.subtle && typeof window.crypto.subtle.digest === 'function');
}

const TOTAL_MS = 800;   // twardy limit calosci
const SIGNALS_MS = 600; // limit zbierania sygnalow, reszta zostaje na liczenie skrotow
const VOICES_MS = 400;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hex = (buf) => Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, '0')).join('');

async function sha256(text) {
  return hex(await window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)));
}

/** Uruchamia sygnal; wyjatek lub odrzucenie daje pusty tekst. */
async function safe(fn) {
  try {
    const v = await fn();
    return v == null ? '' : String(v);
  } catch (e) {
    return '';
  }
}

function iosMinor() {
  const ua = navigator.userAgent || '';
  if (!/(iPhone|iPad|iPod)/.test(ua)) return '';
  const v = /OS (\d+)[_.](\d+)/.exec(ua);
  return v ? v[1] + '.' + v[2] : '';
}

async function highEntropy() {
  const d = navigator.userAgentData;
  if (!d || typeof d.getHighEntropyValues !== 'function') return '';
  const v = await d.getHighEntropyValues(['model', 'platformVersion']);
  return (v.model || '') + '|' + (v.platformVersion || '');
}

const MEDIA = [
  '(prefers-reduced-motion: reduce)',
  '(prefers-contrast: more)', '(prefers-contrast: less)', '(prefers-contrast: custom)',
  '(prefers-reduced-transparency: reduce)',
  '(inverted-colors: inverted)',
  '(forced-colors: active)',
  '(color-gamut: srgb)', '(color-gamut: p3)', '(color-gamut: rec2020)',
  '(dynamic-range: high)',
];

function mediaSignal() {
  return MEDIA.map((q) => {
    try { return window.matchMedia(q).matches ? '1' : '0'; } catch (e) { return '0'; }
  }).join('');
}

function context2d() {
  const c = document.createElement('canvas');
  return c.getContext('2d');
}

// Emoji z nowszych wersji Unicode: tak/nie, czy czcionka systemu je ma (szerokosc jak przy starym emoji).
const EMOJI = ['\u{1F972}', '\u{1F978}', '\u{1F979}', '\u{1FAE0}', '\u{1FAE8}', '\u{1FAF7}', '\u{1FA75}'];

function emojiSignal() {
  const ctx = context2d();
  if (!ctx) return '';
  ctx.font = '32px sans-serif';
  const ref = ctx.measureText('\u{1F600}').width;
  return EMOJI.map((e) => (Math.abs(ctx.measureText(e).width - ref) < 0.5 ? '1' : '0')).join('');
}

const FONTS = [
  'Roboto', 'Noto Sans', 'Droid Sans', 'SamsungOne', 'Samsung Sans', 'Samsung Sharp Sans', 'MiSans', 'MIUI', 'Mi Sans',
  'HarmonyOS Sans', 'HuaweiSans', 'Segoe UI', 'Segoe UI Emoji', 'Calibri', 'Cambria', 'Consolas', 'Tahoma',
  'Verdana', 'Arial', 'Times New Roman', 'Georgia', 'Helvetica', 'Helvetica Neue', 'Menlo', 'Monaco',
  'SF Pro Text', 'Avenir', 'Gill Sans', 'PingFang SC', 'Apple Color Emoji', 'Noto Color Emoji', 'Ubuntu', 'DejaVu Sans',
];

function fontsSignal() {
  const ctx = context2d();
  if (!ctx) return '';
  const text = 'mmmmmmmmmmlli0Oq';
  const bases = ['monospace', 'serif', 'sans-serif'];
  const width = (font) => { ctx.font = '48px ' + font; return ctx.measureText(text).width; };
  const baseW = bases.map((b) => width(b));
  const found = FONTS.filter((f) => bases.some((b, i) => width('"' + f + '", ' + b) !== baseW[i]));
  return found.sort().join(',');
}

async function voicesSignal() {
  const ss = window.speechSynthesis;
  if (!ss || typeof ss.getVoices !== 'function') return '';
  let list = ss.getVoices();
  if (!list.length && typeof ss.addEventListener === 'function') {
    await new Promise((resolve) => {
      const done = () => { ss.removeEventListener('voiceschanged', done); clearTimeout(t); resolve(); };
      const t = setTimeout(done, VOICES_MS);
      ss.addEventListener('voiceschanged', done);
    });
    list = ss.getVoices();
  }
  return Array.from(new Set(list.map((v) => v.name))).sort().join(',');
}

async function quotaSignal() {
  const est = await navigator.storage.estimate();
  const q = Number(est && est.quota);
  return q > 0 ? String(2 ** Math.round(Math.log2(q))) : '';
}

function webglSignal() {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
  if (!gl) return '';
  let renderer = '';
  const info = gl.getExtension('WEBGL_debug_renderer_info');
  if (info) renderer = gl.getParameter(info.UNMASKED_RENDERER_WEBGL) || '';
  const out = renderer + '|' + (gl.getParameter(gl.MAX_TEXTURE_SIZE) || '');
  const lose = gl.getExtension('WEBGL_lose_context');
  if (lose) lose.loseContext();
  return out;
}

/** Sygnaly rozrozniajace egzemplarze: [nazwa, funkcja]; kolejnosc stala. */
const EXT_SIGNALS = [
  ['ios', iosMinor],
  ['lang', () => navigator.language || ''],
  ['uad', highEntropy],
  ['media', mediaSignal],
  ['emoji', emojiSignal],
  ['fonts', fontsSignal],
  ['voices', voicesSignal],
  ['quota', quotaSignal],
  ['gl', webglSignal],
];

/** Sygnaly podstawowe, kazdy osobno w try/catch (pojedynczy blad nie psuje calosci). */
function baseParts() {
  const get = (fn, dflt) => { try { return fn(); } catch (e) { return dflt; } };
  const s = get(() => window.screen, null) || {};
  const w = get(() => Number(s.width) || 0, 0);
  const hgt = get(() => Number(s.height) || 0, 0);
  return [
    get(osSignal, 'other'),
    Math.min(w, hgt) + 'x' + Math.max(w, hgt),
    get(() => s.colorDepth || 0, 0),
    get(() => (Number(window.devicePixelRatio) || 1).toFixed(2), '1.00'),
    get(() => navigator.hardwareConcurrency || 0, 0),
    get(() => navigator.maxTouchPoints || 0, 0),
    timeZone(),
  ];
}

/**
 * Zwraca { base, ext }: dwa skroty SHA-256 (64 znaki hex). Rzuca Error z czytelnym komunikatem tylko wtedy,
 * gdy crypto.subtle jest niedostepne. Nie rzuca z powodu pojedynczego sygnalu i konczy sie w ok. 800 ms.
 */
export async function deviceHashes() {
  if (!deviceHashSupported()) {
    throw new Error('Ta przeglądarka nie pozwala obliczyć identyfikatora urządzenia (wymagane jest bezpieczne połączenie HTTPS). Otwórz grę w aktualnej przeglądarce, np. Chrome lub Safari.');
  }
  const started = Date.now();
  const base = await sha256('hp-device-v1|' + baseParts().join('|'));
  const got = {};
  const jobs = EXT_SIGNALS.map(([name, fn]) => safe(fn).then((v) => { got[name] = v; }));
  const left = Math.max(0, Math.min(SIGNALS_MS, TOTAL_MS - 150 - (Date.now() - started)));
  await Promise.race([Promise.all(jobs), sleep(left)]);
  let ext = base;
  try {
    ext = await sha256('hp-device-ext-v1|' + base + '|' + EXT_SIGNALS.map(([name]) => name + '=' + (got[name] || '')).join('|'));
  } catch (e) { /* ext zostaje rowny base */ }
  return { base, ext };
}
