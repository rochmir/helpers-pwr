import { api, $, countUp } from './common.js';

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
  } catch (e) { /* zostaje sam link */ }
}

revealTimeline();
liveTotal();
