/* ui.js — comportamenti minimi del tema: dropdown, menu mobile,
   mostra/nascondi password, ingresso card e righe tabella, toast. Nessuna dipendenza. */
(function () {
  'use strict';
  document.documentElement.classList.add('js');

  // --- Dropdown (.ui-dropdown > trigger[aria-controls] + .ui-dropdown-menu)
  const closeAllDropdowns = () => {
    document.querySelectorAll('.ui-dropdown.is-open').forEach((dd) => {
      dd.classList.remove('is-open');
      const t = dd.querySelector('[aria-haspopup]');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  };
  document.querySelectorAll('.ui-dropdown').forEach((dd) => {
    const trigger = dd.querySelector('[aria-haspopup]');
    if (!trigger) return;
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const wasOpen = dd.classList.contains('is-open');
      closeAllDropdowns();
      if (!wasOpen) {
        dd.classList.add('is-open');
        trigger.setAttribute('aria-expanded', 'true');
      }
    });
    dd.querySelectorAll('.ui-dropdown-menu a, .ui-dropdown-menu button').forEach((el) => {
      el.addEventListener('click', () => {
        dd.classList.remove('is-open');
        trigger.setAttribute('aria-expanded', 'false');
      });
    });
  });
  document.addEventListener('click', closeAllDropdowns);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeAllDropdowns(); });

  // --- Menu mobile: il bottone .ui-nav-toggle apre/chiude .ui-nav
  const toggle = document.querySelector('.ui-nav-toggle');
  const nav = document.querySelector('.ui-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', () => {
      nav.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
    });
  }

  // --- Mostra/nascondi password: <button data-toggle-password="id_campo">
  document.querySelectorAll('[data-toggle-password]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = document.getElementById(btn.dataset.togglePassword);
      if (!input) return;
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.setAttribute('aria-pressed', String(!showing));
      btn.setAttribute('aria-label', showing ? 'Mostra password' : 'Nascondi password');
      const eyeShow = btn.querySelector('[data-icon-show]');
      const eyeHide = btn.querySelector('[data-icon-hide]');
      if (eyeShow && eyeHide) { eyeShow.hidden = !showing; eyeHide.hidden = showing; }
    });
  });

  // --- Ingresso card: ui.css le tiene a opacity 0 finché non hanno .is-revealed
  const cards = document.querySelectorAll('.ui-card:not(.is-revealed)');
  cards.forEach((card, i) => card.style.setProperty('--card-stagger', i));
  void document.body.offsetWidth; // forza il calcolo degli stili a opacity 0, così la transizione parte
  requestAnimationFrame(() => cards.forEach((c) => c.classList.add('is-revealed')));

  // --- Ingresso righe tabella: le righe partono invisibili (ui.css) e
  //     appaiono a cascata quando la tabella entra nel viewport.
  const tables = document.querySelectorAll('table.ui-table');
  const reveal = (t) => {
    t.querySelectorAll('tbody tr').forEach((tr, i) => tr.style.setProperty('--row-index', i));
    t.classList.add('is-revealed');
  };
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => { if (en.isIntersecting) { reveal(en.target); io.unobserve(en.target); } });
    }, { rootMargin: '0px 0px -10% 0px' });
    tables.forEach((t) => io.observe(t));
  } else {
    tables.forEach(reveal);
  }

  // --- Toast: window.uiToast('Salvato', 'warn'|undefined)
  window.uiToast = function (text, kind) {
    let el = document.querySelector('.ui-toast');
    if (!el) { el = document.createElement('div'); el.className = 'ui-toast'; el.setAttribute('role', 'status'); document.body.appendChild(el); }
    el.textContent = text;
    el.classList.toggle('ui-toast-warn', kind === 'warn');
    requestAnimationFrame(() => el.classList.add('is-visible'));
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('is-visible'), 3000);
  };
})();
