/*
 * Strawpoll premium interactions — no dependencies.
 *   * Scroll reveal via IntersectionObserver (re-initialised after HTMX swaps)
 *   * Subtle 3D hover tilt + light shine on [data-tilt] cards
 *   * Glowing click ripple on .btn-glow buttons
 *   * Selected voting-option highlight
 *   * Animated donut charts built from the REAL percentages the server renders
 *
 * Everything respects prefers-reduced-motion and degrades silently on touch
 * devices or browsers without the needed APIs.
 */
(function () {
  'use strict';

  var reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var finePointer = window.matchMedia &&
    window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  /* --- Scroll reveal ----------------------------------------------------- */
  var observer = ('IntersectionObserver' in window) && !reduceMotion
    ? new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' })
    : null;

  function initReveal(root) {
    (root || document).querySelectorAll('.reveal:not(.is-visible)').forEach(function (el) {
      if (observer) { observer.observe(el); } else { el.classList.add('is-visible'); }
    });
  }

  /* --- 3D hover tilt ------------------------------------------------------ */
  function initTilt(root) {
    if (reduceMotion || !finePointer) return;
    (root || document).querySelectorAll('[data-tilt]:not([data-tilt-on])').forEach(function (card) {
      card.setAttribute('data-tilt-on', '1');
      var rect = null;
      card.addEventListener('mouseenter', function () {
        rect = card.getBoundingClientRect();
      });
      card.addEventListener('mousemove', function (e) {
        if (!rect) rect = card.getBoundingClientRect();
        var px = (e.clientX - rect.left) / rect.width;
        var py = (e.clientY - rect.top) / rect.height;
        var rx = ((0.5 - py) * 7).toFixed(2);
        var ry = ((px - 0.5) * 9).toFixed(2);
        card.style.transform = 'rotateX(' + rx + 'deg) rotateY(' + ry + 'deg) translateY(-3px)';
        card.style.setProperty('--mx', (px * 100).toFixed(1) + '%');
        card.style.setProperty('--my', (py * 100).toFixed(1) + '%');
      });
      card.addEventListener('mouseleave', function () {
        rect = null;
        card.style.transform = '';
      });
    });
  }

  /* --- Glow click ripple --------------------------------------------------- */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.btn-glow');
    if (!btn || reduceMotion) return;
    var rect = btn.getBoundingClientRect();
    var d = Math.max(rect.width, rect.height) * 1.1;
    var ripple = document.createElement('span');
    ripple.className = 'ripple';
    ripple.style.width = ripple.style.height = d + 'px';
    ripple.style.left = (e.clientX - rect.left - d / 2) + 'px';
    ripple.style.top = (e.clientY - rect.top - d / 2) + 'px';
    btn.appendChild(ripple);
    ripple.addEventListener('animationend', function () { ripple.remove(); });
  });

  /* --- Selected voting option ------------------------------------------------ */
  function initVoteOptions(root) {
    (root || document).querySelectorAll('.vote-option input[type="radio"]').forEach(function (input) {
      if (input.dataset.optBound) return;
      input.dataset.optBound = '1';
      input.addEventListener('change', function () {
        var fieldset = input.closest('fieldset');
        if (!fieldset) return;
        fieldset.querySelectorAll('.vote-option').forEach(function (label) {
          label.classList.toggle('is-selected', label.querySelector('input:checked') !== null);
        });
      });
      if (input.checked) input.dispatchEvent(new Event('change'));
    });
  }

  /* --- Animated donut chart ----------------------------------------------------
   * The template renders hidden spans carrying the server-computed percentage
   * for each choice ([data-pct]) and the real ballot total (data-total). This
   * builds an SVG donut from exactly those numbers — no invented statistics. */
  var SEGMENT_COLORS = ['#22d3ee', '#8b5cf6', '#3b82f6', '#f472b6', '#34d399', '#fbbf24', '#a78bfa', '#f87171'];

  function buildDonuts(root) {
    (root || document).querySelectorAll('[data-donut]:not([data-donut-on])').forEach(function (wrap) {
      wrap.setAttribute('data-donut-on', '1');
      var segs = [].slice.call(wrap.querySelectorAll('[data-pct]')).map(function (el, i) {
        return {
          pct: parseFloat(el.getAttribute('data-pct')) || 0,
          color: SEGMENT_COLORS[i % SEGMENT_COLORS.length],
        };
      });
      var totalPct = segs.reduce(function (s, x) { return s + x.pct; }, 0);
      if (!segs.length || totalPct <= 0) { wrap.style.display = 'none'; return; }

      var NS = 'http://www.w3.org/2000/svg';
      var size = 150, stroke = 20, r = (size - stroke) / 2, c = 2 * Math.PI * r;

      var svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('viewBox', '0 0 ' + size + ' ' + size);
      svg.setAttribute('width', '100%');
      svg.setAttribute('height', '100%');
      svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', 'Result distribution chart');

      var accum = 0;
      segs.forEach(function (seg) {
        var circle = document.createElementNS(NS, 'circle');
        circle.setAttribute('cx', size / 2);
        circle.setAttribute('cy', size / 2);
        circle.setAttribute('r', r);
        circle.setAttribute('fill', 'none');
        circle.setAttribute('stroke', seg.color);
        circle.setAttribute('stroke-width', stroke);
        circle.setAttribute('class', 'donut-seg');
        circle.setAttribute('transform',
          'rotate(' + (-90 + (360 * accum / totalPct)).toFixed(3) + ' ' + size / 2 + ' ' + size / 2 + ')');
        var target = (seg.pct / totalPct * c).toFixed(2);
        if (reduceMotion) {
          circle.setAttribute('stroke-dasharray', target + ' ' + (c - target).toFixed(2));
        } else {
          circle.setAttribute('stroke-dasharray', '0 ' + c.toFixed(2));
          circle.dataset.target = target;
        }
        svg.appendChild(circle);
        accum += seg.pct;
      });

      var value = document.createElementNS(NS, 'text');
      value.setAttribute('x', '50%');
      value.setAttribute('y', '48%');
      value.setAttribute('text-anchor', 'middle');
      value.setAttribute('dominant-baseline', 'central');
      value.setAttribute('class', 'donut-center-value');
      value.textContent = wrap.getAttribute('data-total') || '';

      var label = document.createElementNS(NS, 'text');
      label.setAttribute('x', '50%');
      label.setAttribute('y', '61%');
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('class', 'donut-center-label');
      label.textContent = 'BALLOTS';

      // Center text must live INSIDE the svg to render.
      svg.appendChild(value);
      svg.appendChild(label);
      wrap.appendChild(svg);

      if (!reduceMotion) {
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            svg.querySelectorAll('.donut-seg').forEach(function (circle) {
              var v = parseFloat(circle.dataset.target);
              circle.setAttribute('stroke-dasharray', v.toFixed(2) + ' ' + (c - v).toFixed(2));
            });
          });
        });
      }
    });
  }

  /* --- Boot ------------------------------------------------------------------ */
  function initAll(root) {
    initReveal(root);
    initTilt(root);
    initVoteOptions(root);
    buildDonuts(root);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { initAll(document); });
  } else {
    initAll(document);
  }

  /* HTMX swaps (vote -> results, live result refresh) re-run the inits so
     newly swapped bars/donuts animate too. */
  document.body.addEventListener('htmx:afterSwap', function (e) {
    initAll(e.target);
  });
})();
