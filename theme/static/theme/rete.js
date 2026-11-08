/* Tolleranza alla perdita di connessione (PLT-19), su tutte le pagine dell'applicazione:
   - indicatore «Sei offline» finché la rete non torna;
   - gestore globale degli errori HTMX: niente più salvataggi persi in silenzio, un avviso con «Riprova»;
   - bozza locale dei form con data-bozza: se l'invio non arriva al server (o si chiude la scheda), alla riapertura
     si può ripristinare quello che si era scritto.
   Chi gestisce da sé gli errori di una zona (es. la chat) mette data-errori-propri su un suo contenitore. */
(function () {
  'use strict';

  // --- Indicatore di connessione assente
  let barra = null;
  const offline = (motivo) => {
    if (!barra) {
      barra = document.createElement('div');
      barra.className = 'ui-offline';
      barra.setAttribute('role', 'status');
      barra.setAttribute('aria-live', 'polite');
      document.body.appendChild(barra);
    }
    barra.textContent = motivo || 'Sei offline: quello che salvi adesso non arriva al server. Riprova quando torna la connessione.';
    barra.hidden = false;
    document.documentElement.classList.add('is-offline');
  };
  const online = () => {
    if (barra && !barra.hidden) {
      barra.hidden = true;
      if (window.uiToast) window.uiToast('Di nuovo in linea');
    }
    document.documentElement.classList.remove('is-offline');
  };
  window.addEventListener('offline', () => offline());
  window.addEventListener('online', online);
  if (navigator.onLine === false) offline();

  // --- Errori delle richieste HTMX
  const proprio = (d) => {
    const el = d.target || d.elt;
    return !!(el && el.closest && el.closest('[data-errori-propri]'));
  };
  let avviso = null;
  const mostra = (testo, riprova) => {
    if (!avviso) {
      avviso = document.createElement('div');
      avviso.className = 'ui-errore-rete';
      avviso.setAttribute('role', 'alert');
      avviso.innerHTML = '<span></span><button type="button" class="ui-btn ui-btn-secondary ui-btn-sm" data-riprova>Riprova</button>' +
        '<button type="button" class="ui-icon-btn" data-chiudi aria-label="Chiudi"><svg><use href="#icon-x"/></svg></button>';
      avviso.querySelector('[data-chiudi]').addEventListener('click', () => { avviso.hidden = true; });
      document.body.appendChild(avviso);
    }
    avviso.querySelector('span').textContent = testo;
    const bottone = avviso.querySelector('[data-riprova]');
    bottone.hidden = !riprova;
    bottone.onclick = riprova ? () => { avviso.hidden = true; riprova(); } : null;
    avviso.hidden = false;
  };
  // Rifà la stessa richiesta dallo stesso elemento: i valori del form si rileggono dalla pagina, target e swap pure.
  const riprovaDa = (d) => {
    const cfg = d.requestConfig;
    if (!cfg || !window.htmx || !d.elt || !d.elt.isConnected) return null;
    return () => window.htmx.ajax(cfg.verb.toUpperCase(), cfg.path, { source: d.elt, target: d.target });
  };
  const nascondi = () => { if (avviso) avviso.hidden = true; };

  document.addEventListener('htmx:sendError', (e) => {
    if (proprio(e.detail)) return;
    if (navigator.onLine === false) offline();
    mostra('Non riesco a raggiungere il server: la modifica non è stata salvata.', riprovaDa(e.detail));
  });
  document.addEventListener('htmx:timeout', (e) => {
    if (proprio(e.detail)) return;
    mostra('Il server non ha risposto in tempo: la modifica potrebbe non essere stata salvata.', riprovaDa(e.detail));
  });
  document.addEventListener('htmx:responseError', (e) => {
    if (proprio(e.detail)) return;
    const stato = e.detail.xhr ? e.detail.xhr.status : 0;
    if (stato === 401 || stato === 403) {
      mostra(stato === 401 ? 'La sessione è scaduta: ricarica la pagina e accedi di nuovo.' : 'Non hai il permesso per questa operazione.', null);
    } else if (stato === 404) {
      mostra('Non trovato: forse è stato eliminato da qualcun altro. Ricarica la pagina.', null);
    } else if (stato === 413) {
      mostra('Il file è troppo grande per essere caricato.', null);
    } else if (stato >= 500) {
      mostra(`Errore del server (${stato}): la modifica non è stata salvata.`, riprovaDa(e.detail));
    } else {
      mostra(`La richiesta non è andata a buon fine (${stato}).`, null);
    }
  });
  document.addEventListener('htmx:afterRequest', (e) => {
    if (e.detail.successful) { nascondi(); if (barra && !barra.hidden && navigator.onLine !== false) online(); }
  });

  // --- Bozza locale dei form (data-bozza="<id utente>")
  const PREFISSO = 'bozza:';
  const DURATA = 7 * 24 * 3600 * 1000;
  const memoria = {
    leggi(k) { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch (_) { return null; } },
    scrivi(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* quota o storage bloccato */ } },
    togli(k) { try { localStorage.removeItem(k); } catch (_) { /* niente */ } },
    chiavi() { try { return Object.keys(localStorage).filter((k) => k.startsWith(PREFISSO)); } catch (_) { return []; } },
  };
  const ESCLUSI = new Set(['password', 'file', 'hidden', 'submit', 'button', 'reset', 'image']);
  const campi = (form) => Array.from(form.elements).filter((c) => c.name && !ESCLUSI.has(c.type) && c.name !== 'csrfmiddlewaretoken' && !c.disabled);
  const valori = (form) => {
    const v = {};
    campi(form).forEach((c) => {
      if (c.type === 'checkbox' || c.type === 'radio') { (v[c.name] = v[c.name] || []); if (c.checked) v[c.name].push(c.value); }
      else if (c.multiple) v[c.name] = Array.from(c.selectedOptions).map((o) => o.value);
      else v[c.name] = c.value;
    });
    return v;
  };
  const applica = (form, v) => {
    campi(form).forEach((c) => {
      if (!(c.name in v)) return;
      const x = v[c.name];
      if (c.type === 'checkbox' || c.type === 'radio') c.checked = Array.isArray(x) && x.includes(c.value);
      else if (c.multiple) Array.from(c.options).forEach((o) => { o.selected = Array.isArray(x) && x.includes(o.value); });
      else c.value = x;
      c.dispatchEvent(new Event('change', { bubbles: true }));
    });
  };
  const uguali = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  // Le bozze inviate: se si carica una qualsiasi pagina dell'applicazione, il server ha risposto e non servono più.
  // Quella del form appena riaperto si guarda prima di toglierla: se l'invio non era arrivato, si può ripristinare.
  const oraAdesso = Date.now();
  const forms = Array.from(document.querySelectorAll('form[data-bozza]'));
  const chiaveDi = (form, i) => `${PREFISSO}${form.dataset.bozza}:${location.pathname}:${form.id || i}`;
  const qui = new Set(forms.map(chiaveDi));
  memoria.chiavi().forEach((k) => {
    const b = memoria.leggi(k);
    if (!b || oraAdesso - (b.ora || 0) > DURATA || (b.inviata && !qui.has(k))) memoria.togli(k);
  });

  forms.forEach((form, i) => {
    const chiave = chiaveDi(form, i);
    const iniziali = valori(form);
    const salvata = memoria.leggi(chiave);
    // Un form tornato con errori ha già i valori inviati: niente da ripristinare.
    if (salvata && !(salvata.inviata && form.hasAttribute('data-con-errori')) && !uguali(salvata.valori, iniziali)) {
      const ora = new Date(salvata.ora).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
      const box = document.createElement('div');
      box.className = 'ui-alert ui-alert-warning ui-bozza';
      box.setAttribute('role', 'status');
      box.innerHTML = `<span>${salvata.inviata ? 'L\'ultimo invio di questo modulo potrebbe non essere arrivato.' : 'C\'è una bozza non salvata di questo modulo.'} ` +
        `(${ora})</span> <button type="button" class="ui-btn ui-btn-primary ui-btn-sm" data-ripristina>Ripristina</button> ` +
        '<button type="button" class="ui-btn ui-btn-ghost ui-btn-sm" data-scarta>Scarta</button>';
      box.querySelector('[data-ripristina]').addEventListener('click', () => { applica(form, salvata.valori); box.remove(); });
      box.querySelector('[data-scarta]').addEventListener('click', () => { memoria.togli(chiave); box.remove(); });
      form.prepend(box);
    } else if (salvata) {
      memoria.togli(chiave);
    }
    let timer = null;
    const registra = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const v = valori(form);
        if (uguali(v, iniziali)) memoria.togli(chiave);
        else memoria.scrivi(chiave, { ora: Date.now(), valori: v });
      }, 400);
    };
    form.addEventListener('input', registra);
    form.addEventListener('change', registra);
    form.addEventListener('submit', () => {
      clearTimeout(timer);
      const v = valori(form);
      if (!uguali(v, iniziali)) memoria.scrivi(chiave, { ora: Date.now(), valori: v, inviata: true });
    });
  });

  // All'uscita le bozze di questo browser si cancellano: su un computer condiviso non restano a chi entra dopo.
  document.addEventListener('submit', (e) => {
    if (e.target.closest && e.target.closest('.ui-logout-form')) memoria.chiavi().forEach((k) => memoria.togli(k));
  });
})();
