/* ============================================================
   PayloadOne Docs — Interactive behaviour
   assets/main.js
   ============================================================ */

/* ── Copy-to-clipboard ────────────────────────────────────── */
function initCopyButtons() {
  document.querySelectorAll('.code-block__copy').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const pre = btn.closest('.code-block').querySelector('pre');
      // Extract plain text, stripping HTML tokens
      const text = pre.innerText
        .split('\n')
        .filter((line) => !line.startsWith('# OUTPUT'))
        .join('\n')
        .trim();

      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = 'COPIED';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.textContent = 'COPY';
          btn.classList.remove('copied');
        }, 2000);
      } catch {
        btn.textContent = 'ERROR';
        setTimeout(() => (btn.textContent = 'COPY'), 2000);
      }
    });
  });
}

/* ── Active sidebar link on scroll ───────────────────────── */
function initScrollSpy() {
  const sections = document.querySelectorAll('.section[id]');
  const navLinks = document.querySelectorAll('.sidebar__nav a');

  if (!sections.length || !navLinks.length) return;

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const id = entry.target.id;
          navLinks.forEach((link) => {
            link.classList.toggle('active', link.getAttribute('href') === `#${id}`);
          });
        }
      });
    },
    {
      rootMargin: '-20% 0px -70% 0px',
      threshold: 0,
    }
  );

  sections.forEach((section) => observer.observe(section));
}

/* ── Smooth scroll for sidebar links ─────────────────────── */
function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener('click', (e) => {
      const target = document.querySelector(anchor.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });
}

/* ── Duplicate ticker content for seamless loop ──────────── */
function initTicker() {
  const inner = document.querySelector('.ticker__inner');
  if (!inner) return;
  inner.innerHTML += inner.innerHTML;
}

/* ── Highlight current time in topbar ────────────────────── */
function initClock() {
  const el = document.getElementById('topbar-time');
  if (!el) return;

  function tick() {
    const now = new Date();
    el.textContent = now.toUTCString().replace('GMT', 'UTC');
  }

  tick();
  setInterval(tick, 1000);
}

/* ── Boot ─────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initCopyButtons();
  initScrollSpy();
  initSmoothScroll();
  initTicker();
  initClock();
});