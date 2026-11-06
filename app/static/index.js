import { api, $, h, countUp, formatDateRange } from './common.js';

/** Os czasu: kroki pojawiaja sie kolejno przy wjezdzie w viewport (bez JS wszystko jest widoczne). */
function revealTimeline() {
  const list = $('#timeline');
  if (!list || !('IntersectionObserver' in window)) return;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const steps = [...list.children];
  list.classList.add('js-reveal');
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      // widoczny albo juz przewiniety powyzej ekranu
      if (!e.isIntersecting && e.boundingClientRect.top > 0) continue;
      const i = steps.indexOf(e.target);
      e.target.style.transitionDelay = (i * 0.15) + 's';
      e.target.classList.add('in');
      io.unobserve(e.target);
    }
  }, { threshold: 0, rootMargin: '0px 0px -10% 0px' });
  steps.forEach((s) => io.observe(s));
}

/** Odmiana: 1 zarejestrowany Dawca, 2-4 zarejestrowani Dawcy, reszta zarejestrowanych Dawcow. */
function dawcy(n) {
  if (n === 1) return 'zarejestrowany Dawca';
  const m10 = n % 10, m100 = n % 100;
  if (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) return 'zarejestrowani Dawcy';
  return 'zarejestrowanych Dawców';
}

async function liveTotal() {
  try {
    const s = await api('GET', '/api/stats/live');
    const total = Number(s.total);
    if (!Number.isFinite(total)) return;
    const num = $('#live-total'), label = $('#live-label');
    num.hidden = false;
    label.hidden = false;
    label.textContent = dawcy(total);
    countUp(num, 0, total, 1000, () => { label.textContent = dawcy(total); });
    const a = Number(s.total_actual) || 0;
    if (a > 0) {
      $('#live-p').textContent = Number(s.total_potential) || 0;
      $('#live-a').textContent = a;
      $('#live-split').hidden = false;
    }
  } catch (e) { /* zostaje sam link */ }
}

/** Lista stoisk z terminami (te same dane i formatowanie dat co w /graj). */
async function loadBooths() {
  const list = $('#booth-places'), empty = $('#booth-empty');
  try {
    const d = await api('GET', '/api/booths/public');
    const booths = d.booths || [];
    if (!booths.length) { empty.hidden = false; return; }
    for (const b of booths) {
      list.append(h('li', {},
        b.building ? h('strong', { class: 'place-building' }, b.building) : null,
        h('span', { class: 'place-name' }, b.name),
        h('span', { class: 'place-dates' }, formatDateRange(b.date_from, b.date_to))));
    }
    list.hidden = false;
    if (d.hours) {
      $('#booth-hours').textContent = 'Godziny: ' + d.hours;
      $('#booth-hours').hidden = false;
    }
  } catch (e) {
    empty.hidden = false;
  }
}

revealTimeline();
liveTotal();
loadBooths();
