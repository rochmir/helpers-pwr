// Jednoreki bandyta: rzad bebnow (domyslnie 10). Kazdy beben pokazuje 3 symbole (poprzedni / aktualny / nastepny),
// srodkowy lezy na linii wyplat. Bebny startuja razem (rozmycie ruchu), po czym zatrzymuja sie kolejno od lewej:
// im dalej, tym dluzej i wolniej (napiecie), a kazdy hamuje z lekkim przeregulowaniem (odbicie).
// Uzywane na /graj (maszyna gracza) i na ekranie stoiska (nakladka "Zebrano Genotyp 10/10!").
import { h, sleep, SHAPE_ICONS, SHAPE_NAMES } from './common.js';

export function prefersReducedMotion() {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
}

const rnd = () => Math.floor(Math.random() * 4);
const LOOP = 8; // dlugosc petli ciaglego przewijania (w komorkach)

function cell(n) {
  const idx = Number(n);
  const ok = idx >= 0 && idx < SHAPE_ICONS.length;
  return h('div', { class: 'reel-cell' },
    ok ? h('i', { class: 'ti ' + SHAPE_ICONS[idx] + ' shape-' + idx, 'aria-hidden': 'true' })
       : h('i', { class: 'ti ti-question-mark shape-x', 'aria-hidden': 'true' }));
}

function fill(strip, symbols) {
  strip.textContent = '';
  for (const n of symbols) strip.append(cell(n));
  strip.style.transform = '';
}

/** Buduje rzad bebnow w container (bez animacji; stan spoczynku z znakami zapytania). Zwraca tablice bebnow. */
export function buildReels(container, count = 10) {
  container.textContent = '';
  container.classList.add('reel-bank');
  container.classList.remove('tension');
  const reels = [];
  for (let i = 0; i < count; i++) {
    const strip = h('div', { class: 'reel-strip' });
    const el = h('div', { class: 'reel idle' }, strip);
    el.style.setProperty('--i', i);
    fill(strip, ['x', 'x', 'x']);
    container.append(el);
    reels.push({ el, strip, anim: null });
  }
  return reels;
}

/** Pokazuje stala kolumne 3 symboli (srodkowy = symbol). */
function settle(r, symbol) {
  if (r.anim) { r.anim.cancel(); r.anim = null; }
  fill(r.strip, [rnd(), symbol, rnd()]);
  r.el.classList.remove('idle', 'spinning', 'slow', 'tense');
  r.el.classList.add('landed');
}

/** Ustawia bebny w stanie spoczynku na podanym genotypie (bez animacji); target: opcjonalny wzor do oznaczenia zgodnosci. */
export function showReels(container, genotype, target) {
  const reels = buildReels(container);
  const g = String(genotype || '');
  reels.forEach((r, i) => {
    settle(r, Number(g[i]));
    if (target) r.el.classList.add(g[i] === target[i] ? 'match' : 'miss');
  });
  container.setAttribute('role', 'img');
  container.setAttribute('aria-label', 'Genotyp: ' + [...g].map((c) => SHAPE_NAMES[Number(c)] || '?').join(', '));
}

function startSpin(r, i, reduced) {
  r.el.classList.remove('idle', 'landed', 'match', 'miss', 'pop');
  r.el.classList.add('spinning');
  const loop = Array.from({ length: LOOP }, rnd);
  fill(r.strip, loop.concat(loop)); // dwie kopie => bezszwowa petla translateY(0 -> -50%)
  r.strip.dataset.loop = loop.join('');
  if (reduced) { fill(r.strip, ['x', 'x', 'x']); return; }
  r.anim = r.strip.animate(
    [{ transform: 'translateY(0)' }, { transform: 'translateY(-50%)' }],
    { duration: 300 + (i % 3) * 25, iterations: Infinity, easing: 'linear' });
  r.anim.currentTime = Math.random() * 300;
}

/** Hamowanie bebna: od aktualnego polozenia przewijania do symbolu, z przeregulowaniem. Zwraca Promise po zatrzymaniu. */
function landMotion(r, symbol, decelMs, extraCells) {
  const cellH = r.el.clientHeight / 3;
  const loop = (r.strip.dataset.loop || '0000').split('').map(Number);
  let off = 0;
  if (r.anim) {
    const ty = new DOMMatrix(getComputedStyle(r.strip).transform).m42;
    off = Math.max(0, -ty / cellH) % LOOP;
    r.anim.cancel();
    r.anim = null;
  }
  const i0 = Math.floor(off);
  const frac = off - i0;
  const cells = [];
  for (let k = 0; k < 4; k++) cells.push(loop[(i0 + k) % LOOP]);
  const nf = 5 + extraCells;
  for (let k = 0; k < nf; k++) cells.push(rnd());
  cells.push(rnd(), symbol, rnd());
  fill(r.strip, cells);
  const start = -frac * cellH;
  const final = -(4 + nf) * cellH;
  const over = final - cellH * 0.28;
  r.el.classList.remove('spinning');
  r.el.classList.add('braking');
  const a = r.strip.animate([
    { transform: 'translateY(' + start + 'px)', easing: 'cubic-bezier(.22,.55,.3,1)' },
    { transform: 'translateY(' + over + 'px)', offset: 0.8, easing: 'cubic-bezier(.4,0,.3,1)' },
    { transform: 'translateY(' + final + 'px)' },
  ], { duration: decelMs, fill: 'forwards' });
  r.anim = a;
  return a.finished.catch(() => {}).then(() => {
    if (r.anim === a) { a.cancel(); r.anim = null; }
    fill(r.strip, cells.slice(-3)); // czysty stan: 3 komorki, srodkowa = wynik
    r.el.classList.remove('braking');
  });
}

function fadeIn(r, symbol) {
  settle(r, symbol);
  r.el.classList.add('fade-in');
}

/**
 * Kreci bebnami i zatrzymuje je kolejno na znakach `target` (string albo Promise<string>).
 * opts:
 *   onStop(i, symbol, reelEl)   po wyladowaniu kazdego bebna
 *   onTension(on)               wlaczenie / wylaczenie fazy napiecia (ostatnie bebny)
 *   tension: () => boolean      czy dodac dodatkowe napiecie (np. wynik >= 8), liczone po nadejsciu target
 *   reduced                     prefers-reduced-motion: bez rozmycia i odbicia, bebny ladują po kolei w ok. 1,5 s
 *   speed                       mnoznik czasow (np. 1.2 dla ekranu stoiska)
 * Zwraca Promise<string> po zatrzymaniu wszystkich; przy odrzuconym target bebny wracaja do stanu spoczynku.
 */
export async function spinReels(container, target, opts = {}) {
  const { onStop, onTension, tension, reduced = prefersReducedMotion(), speed = 1 } = opts;
  const reels = buildReels(container);
  const targetP = Promise.resolve(target);
  reels.forEach((r, i) => startSpin(r, i, reduced));
  if (reduced) container.classList.add('calm');
  else container.classList.remove('calm');

  const t0 = performance.now();
  let g;
  try {
    g = String(await targetP);
  } catch (e) {
    reels.forEach((r) => { if (r.anim) r.anim.cancel(); });
    buildReels(container);
    throw e;
  }
  const tense = !reduced && typeof tension === 'function' && !!tension();

  // Plan zatrzymywania (ms od startu): pierwsze bebny szybko jeden po drugim, trzy ostatnie z rosnacym odstepem.
  const plan = reels.map((_, i) => {
    if (reduced) return { at: 350 + i * 110, decel: 0, extra: 0 };
    const fast = [1000, 1240, 1480, 1720, 1960, 2200, 2440];
    if (i < fast.length) return { at: fast[i] * speed, decel: 560 * speed, extra: 0 };
    const late = [2800, 3250, 3750][i - fast.length] || 3750;
    const hold = tense && i >= 8 ? (i === 8 ? 400 : 650) : 0;
    return { at: (late + hold) * speed, decel: [750, 900, 1100][i - fast.length] * speed, extra: 2 + (i - fast.length) * 2 };
  });

  const jobs = reels.map(async (r, i) => {
    const p = plan[i];
    if (!reduced && i === 7) {
      // Faza napiecia: ostatnie bebny zwalniaja i swieca.
      const wait = Math.max(0, plan[6].at + 250 * speed - (performance.now() - t0));
      await sleep(wait);
      container.classList.add('tension-late');
      if (tense) container.classList.add('tension');
      for (const rr of reels.slice(7)) {
        rr.el.classList.add('slow');
        if (tense) rr.el.classList.add('tense');
        if (rr.anim) rr.anim.playbackRate = 0.5;
      }
      if (onTension) onTension(true);
    }
    await sleep(Math.max(0, p.at - (performance.now() - t0)));
    if (reduced) {
      fadeIn(r, Number(g[i]));
    } else {
      await landMotion(r, Number(g[i]), p.decel, p.extra);
      r.el.classList.remove('slow', 'tense');
      r.el.classList.add('landed');
    }
    if (onStop) onStop(i, g[i], r.el);
  });
  await Promise.all(jobs);
  container.classList.remove('tension', 'tension-late');
  if (onTension) onTension(false);
  container.setAttribute('role', 'img');
  container.setAttribute('aria-label', 'Genotyp: ' + [...g].map((c) => SHAPE_NAMES[Number(c)] || '?').join(', '));
  return g;
}

/** Konfetti z div-ow w barwach marki (bez bibliotek). Zwraca element; sam znika po `lifeMs`. */
export function confetti(host = document.body, { count = 70, lifeMs = 6500 } = {}) {
  if (prefersReducedMotion()) return null;
  const colors = ['#e2001a', '#f9ccd1', '#30783e', '#2c5a82', '#ffb500', '#ffffff'];
  const box = h('div', { class: 'confetti', 'aria-hidden': 'true' });
  for (let i = 0; i < count; i++) {
    const p = h('i', { class: 'confetti-piece' });
    p.style.setProperty('--x', (Math.random() * 100).toFixed(1) + '%');
    p.style.setProperty('--d', (2.8 + Math.random() * 2.6).toFixed(2) + 's');
    p.style.setProperty('--delay', (Math.random() * 1.6).toFixed(2) + 's');
    p.style.setProperty('--r', Math.floor(Math.random() * 720 - 360) + 'deg');
    p.style.setProperty('--sway', Math.floor(Math.random() * 120 - 60) + 'px');
    p.style.setProperty('--w', (6 + Math.random() * 8).toFixed(0) + 'px');
    p.style.setProperty('--c', colors[i % colors.length]);
    if (i % 3 === 0) p.classList.add('round');
    box.append(p);
  }
  host.append(box);
  setTimeout(() => box.remove(), lifeMs);
  return box;
}

