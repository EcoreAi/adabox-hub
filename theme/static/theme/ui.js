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

  // --- Verifica in due passaggi: 6 cifre e parte da sola; codice di recupero; copia dei codici
  document.querySelectorAll('[data-df-codice]').forEach((campo) => {
    campo.addEventListener('input', () => {
      if (campo.classList.contains('is-recupero')) return;
      campo.value = campo.value.replace(/\D/g, '').slice(0, 6);
      if (campo.value.length === 6) campo.form.requestSubmit();
    });
  });
  document.querySelectorAll('[data-df-recupero]').forEach((bottone) => {
    bottone.addEventListener('click', () => {
      const campo = bottone.closest('form').querySelector('[data-df-codice]');
      campo.classList.add('is-recupero');
      campo.removeAttribute('pattern');
      campo.inputMode = 'text';
      campo.autocomplete = 'off';
      campo.maxLength = 9;
      campo.placeholder = 'XXXX-XXXX';
      campo.value = '';
      campo.focus();
      bottone.closest('p').hidden = true;
    });
  });
  document.querySelectorAll('[data-df-copia]').forEach((bottone) => {
    bottone.addEventListener('click', async () => {
      const voci = [...document.getElementById(bottone.dataset.dfCopia).children].map((li) => li.textContent);
      await navigator.clipboard.writeText(voci.join('\n'));
      window.uiToast('Codici copiati');
    });
  });

  // --- Cronometro delle ore nella barra in alto
  document.querySelectorAll('[data-cronometro-da]').forEach((el) => {
    const da = Number(el.dataset.cronometroDa);
    const due = (n) => String(n).padStart(2, '0');
    const scrivi = () => {
      const s = Math.max(0, Math.floor(Date.now() / 1000) - da);
      el.textContent = `${due(Math.floor(s / 3600))}:${due(Math.floor(s / 60) % 60)}:${due(s % 60)}`;
    };
    scrivi();
    setInterval(scrivi, 1000);
  });
  // --- Guida: articoli suggeriti mentre si scrive l'oggetto
  document.querySelectorAll('[data-guida-cerca]').forEach((campo) => {
    const elenco = document.getElementById(campo.dataset.guidaCerca);
    let attesa;
    campo.addEventListener('input', () => {
      clearTimeout(attesa);
      attesa = setTimeout(async () => {
        const testo = campo.value.trim();
        if (testo.length < 3) { elenco.hidden = true; return; }
        const risposta = await fetch(`${elenco.dataset.url}?q=${encodeURIComponent(testo)}`, { credentials: 'same-origin' });
        if (!risposta.ok) return;
        const { articoli } = await risposta.json();
        elenco.replaceChildren(...articoli.map((a) => {
          const voce = document.createElement('a');
          voce.href = a.url; voce.target = '_blank'; voce.rel = 'noopener'; voce.textContent = a.titolo;
          return voce;
        }));
        elenco.hidden = !articoli.length;
      }, 300);
    });
  });

  // --- Fatturazione delle ore: il totale segue le righe scelte
  document.querySelectorAll('[data-ore-form]').forEach((form) => {
    const totale = form.querySelector('[data-ore-totale]');
    const ore = form.querySelector('[data-ore-somma]');
    const formato = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' });
    const ricalcola = () => {
      let euro = 0; let h = 0;
      form.querySelectorAll('[data-ore-riga]:checked').forEach((c) => { euro += Number(c.dataset.importo); h += Number(c.dataset.ore); });
      totale.textContent = formato.format(euro);
      ore.textContent = h.toLocaleString('it-IT', { maximumFractionDigits: 2 });
    };
    form.addEventListener('change', ricalcola);
    ricalcola();
  });
})();
