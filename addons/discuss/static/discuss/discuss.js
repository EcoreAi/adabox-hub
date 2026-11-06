// Comunicazioni: tempo reale, azioni sui messaggi, scrittura (forme, @, #, emoji, file, vocali), pannelli e ricerca.
(function () {
  const app = document.getElementById('ds-app');
  if (!app) return;
  const canale = app.dataset.canale;
  const lista = document.getElementById('ds-messaggi');
  const pannello = document.getElementById('ds-pannello');
  const toast = document.getElementById('ds-toast');
  const io = app.dataset.io;
  const csrf = () => (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';

  function avvisa(testo) {
    toast.textContent = testo; toast.hidden = false;
    clearTimeout(avvisa.t); avvisa.t = setTimeout(() => { toast.hidden = true; }, 5000);
  }
  // i pulsanti htmx fuori da un form: il token sta nella pagina
  document.body.addEventListener('htmx:configRequest', (ev) => { if (ev.detail.verb !== 'get') ev.detail.headers['X-CSRFToken'] = csrf(); });
  const post = (url, dati = {}) => fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded', 'HX-Request': 'true' }, body: new URLSearchParams(dati) });

  // --- scorrimento ---
  const inFondo = () => !lista || lista.scrollHeight - lista.scrollTop - lista.clientHeight < 120;
  const vaiInFondo = () => { if (lista) lista.scrollTop = lista.scrollHeight; };
  // si scorre solo l'elenco dei messaggi: scrollIntoView trascinerebbe anche la pagina
  function mostra(el, dove) {
    const contenitore = el.closest('.ds-messaggi, .ds-pannello-corpo') || lista;
    const delta = el.getBoundingClientRect().top - contenitore.getBoundingClientRect().top;
    contenitore.scrollTop += dove === 'center' ? delta - (contenitore.clientHeight - el.offsetHeight) / 2 : delta;
  }
  function vaiA(id) {
    const el = document.getElementById(`m${id}`);
    if (!el) return false;
    mostra(el, 'center');
    el.classList.remove('is-evidente'); void el.offsetWidth; el.classList.add('is-evidente');
    return true;
  }
  const primoNuovo = document.getElementById('ds-primo-nuovo');
  if (app.dataset.bersaglio) vaiA(app.dataset.bersaglio);
  else if (location.hash.startsWith('#m') && vaiA(location.hash.slice(2))) { /* arrivato da una notifica */ }
  else if (primoNuovo) mostra(primoNuovo, 'start');
  else vaiInFondo();

  let eraInFondo = true;
  document.body.addEventListener('htmx:beforeSwap', (ev) => { if (ev.detail.target && ev.detail.target.id === 'ds-poller') eraInFondo = inFondo(); });
  document.body.addEventListener('htmx:afterSwap', (ev) => {
    if (!lista || !ev.detail.target) return;
    if (ev.detail.target.id === 'ds-poller' || ev.detail.elt?.id === 'ds-poller') {
      const vuoto = lista.querySelector('[data-vuoto]');
      if (vuoto && lista.querySelector('.ds-messaggio, .ds-avviso-riga')) vuoto.remove();
      if (eraInFondo) vaiInFondo();
    }
  });

  // --- tempo reale ---
  const baseTitolo = document.title;
  let nonVisti = 0;
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { nonVisti = 0; document.title = baseTitolo; } });
  let barraTimer;
  function aggiornaBarra() {
    clearTimeout(barraTimer);
    barraTimer = setTimeout(() => {
      const url = `${app.dataset.barra}${canale ? `?corrente=${canale}` : ''}`;
      htmx.ajax('GET', url, { target: '#ds-barra', swap: 'innerHTML' });
    }, 250);
  }
  const scrivono = new Map();
  const riga = document.getElementById('ds-digita');
  function disegnaScrivono() {
    if (!riga) return;
    const ora = Date.now();
    for (const [k, v] of scrivono) if (v.fino < ora) scrivono.delete(k);
    const nomi = [...scrivono.values()].map((v) => v.nome);
    riga.textContent = !nomi.length ? '' : nomi.length === 1 ? `${nomi[0]} sta scrivendo…` : `${nomi.join(', ')} stanno scrivendo…`;
  }
  setInterval(disegnaScrivono, 1000);

  function aggiornaMessaggio(id) {
    const el = document.getElementById(`m${id}`);
    if (!el || el.matches('form')) return;       // chi sta modificando non perde il testo
    if (el.querySelector('details[open]')) return;
    htmx.ajax('GET', app.dataset.messaggio.replace('/0/', `/${id}/`), { target: `#m${id}`, swap: 'outerHTML' });
  }
  function suEvento(dati) {
    const qui = canale && String(dati.canale) === String(canale);
    if (dati.tipo === 'nuovo') {
      if (qui) document.body.dispatchEvent(new Event('ds-nuovi'));
      if (!qui || document.hidden) aggiornaBarra();
      if (qui && dati.autore) { scrivono.delete(String(dati.autore)); disegnaScrivono(); }
      if (document.hidden && String(dati.autore) !== io && !dati.avviso) { nonVisti += 1; document.title = `(${nonVisti}) ${baseTitolo}`; }
    } else if (dati.tipo === 'agg' && qui) {
      aggiornaMessaggio(dati.m);
      if (dati.n_fissati !== undefined) { const n = document.getElementById('ds-n-fissati'); if (n) n.textContent = dati.n_fissati || ''; }
    } else if (dati.tipo === 'scrive' && qui && String(dati.autore) !== io) {
      scrivono.set(String(dati.autore), { nome: dati.nome, fino: Date.now() + 5000 }); disegnaScrivono();
    } else if (dati.tipo === 'chiamata') {
      if (dati.squilla && String(dati.autore) !== io && window.dsSquillo) window.dsSquillo.squilla(dati.token, dati.nome, dati.url, dati.video);
    } else if (dati.tipo === 'chiamata_fine') {
      if (window.dsSquillo) window.dsSquillo.togli(dati.token);
    } else if (dati.tipo === 'barra') {
      aggiornaBarra();
    } else if (dati.tipo === 'notifica') {
      aggiornaBarra();
      if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
        const n = new Notification(dati.titolo, { body: dati.testo });
        n.onclick = () => { window.focus(); location.href = dati.url; };
      }
    }
  }
  if (window.EventSource) {
    const param = new URLSearchParams({ dopo: app.dataset.evento || '0' });
    if (canale) param.set('canale', canale);
    const fonte = new EventSource(`${app.dataset.eventi}?${param}`);
    fonte.addEventListener('discuss', (ev) => { try { suEvento(JSON.parse(ev.data)); } catch (e) { /* evento illeggibile */ } });
    window.addEventListener('pagehide', () => fonte.close());
  }

  // --- pannelli laterali ---
  function chiudiPannello() { pannello.hidden = true; pannello.textContent = ''; app.classList.remove('con-pannello'); pannello.dataset.url = ''; }
  function apriPannello(url) {
    if (pannello.dataset.url === url && !pannello.hidden) { chiudiPannello(); return; }
    pannello.dataset.url = url; pannello.hidden = false; app.classList.add('con-pannello');
    htmx.ajax('GET', url, { target: '#ds-pannello', swap: 'innerHTML' });
  }

  // azioni di una scheda: il bottone del record gira nel suo modulo, poi la scheda si ridisegna
  document.body.addEventListener('htmx:afterRequest', (ev) => {
    const btn = ev.detail.elt;
    if (!btn || !btn.matches || !btn.matches('[data-scheda-azione]') || !ev.detail.successful) return;
    const scheda = btn.closest('.ds-scheda');
    if (scheda) htmx.ajax('GET', scheda.dataset.url, { target: scheda, swap: 'outerHTML' });
  });

  // --- dialoghi e scelta delle persone ---
  document.addEventListener('input', (ev) => {
    const filtro = ev.target.closest('[data-scelta-filtro]');
    if (!filtro) return;
    const q = filtro.value.trim().toLowerCase();
    filtro.closest('[data-scelta]').querySelectorAll('.ds-scelta-voce').forEach((v) => { v.hidden = q && !v.dataset.nome.includes(q); });
  });

  // --- selettore delle emoji ---
  const EMOJI = '👍 👎 ❤️ 🔥 🎉 👏 🙌 🙏 😀 😄 😂 🤣 😊 😍 🤔 😮 😢 😡 😎 🥳 🤝 💪 ✅ ❌ ⚠️ ❓ 💡 📌 📎 📅 🚀 ⭐ ☕ 🍕 👀'.split(' ');
  let selettore;
  function chiudiEmoji() { if (selettore) { selettore.remove(); selettore = null; } }
  function apriEmoji(ancora, scelta) {
    chiudiEmoji();
    selettore = document.createElement('div');
    selettore.className = 'ds-emoji';
    selettore.setAttribute('role', 'listbox');
    EMOJI.forEach((e) => {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = e; b.setAttribute('aria-label', e);
      b.addEventListener('click', () => { chiudiEmoji(); scelta(e); });
      selettore.appendChild(b);
    });
    document.body.appendChild(selettore);
    const r = ancora.getBoundingClientRect(), a = selettore.getBoundingClientRect();
    selettore.style.left = `${Math.max(8, Math.min(r.left, innerWidth - a.width - 8))}px`;
    selettore.style.top = `${r.top - a.height - 6 > 8 ? r.top - a.height - 6 : r.bottom + 6}px`;
  }
  function reagisci(id, emoji) {
    const url = app.dataset.reazione.replace('/0/', `/${id}/`);
    htmx.ajax('POST', url, { target: `#m${id}`, swap: 'outerHTML', values: { emoji } });
  }

  document.addEventListener('click', (ev) => {
    const t = ev.target;
    if (selettore && !t.closest('.ds-emoji') && !t.closest('[data-emoji-reazione],[data-emoji-testo]')) chiudiEmoji();
    document.querySelectorAll('.ds-altro[open]').forEach((d) => { if (!d.contains(t)) d.open = false; });

    const dialogo = t.closest('[data-apri]');
    if (dialogo) { document.getElementById(dialogo.dataset.apri).showModal(); return; }
    if (t.closest('[data-chiudi]')) { t.closest('dialog').close(); return; }
    if (t.closest('[data-chiudi-pannello]')) { chiudiPannello(); return; }
    const aprePannello = t.closest('[data-pannello]');
    if (aprePannello) { apriPannello(aprePannello.dataset.pannello); return; }

    const vai = t.closest('[data-vai]');
    if (vai && vaiA(vai.dataset.vai)) { ev.preventDefault(); return; }

    const msg = t.closest('.ds-messaggio');
    // con il tocco non c'è il passaggio del mouse: gli strumenti si aprono sul messaggio toccato, uno alla volta
    if (window.matchMedia('(hover: none)').matches) {
      document.querySelectorAll('.ds-messaggio.is-toccato').forEach((m) => { if (m !== msg) m.classList.remove('is-toccato'); });
      if (msg && !t.closest('a, button, summary, audio, textarea')) msg.classList.toggle('is-toccato');
    }
    const rapida = t.closest('[data-reagisci]');
    if (rapida && msg) { reagisci(msg.dataset.id, rapida.dataset.reagisci); return; }
    const altra = t.closest('[data-emoji-reazione]');
    if (altra && msg) { apriEmoji(altra, (e) => reagisci(msg.dataset.id, e)); return; }
    const leggi = t.closest('[data-da-leggere]');
    if (leggi) { post(leggi.dataset.daLeggere).then(() => avvisa('Conversazione segnata da leggere fino alla prossima apertura.')); return; }
    const copia = t.closest('[data-copia-link]');
    if (copia) {
      const url = location.origin + copia.dataset.copiaLink;
      const ok = navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject();
      ok.then(() => avvisa('Link copiato.'), () => avvisa(url));
      copia.closest('details').open = false;
      return;
    }
    const rispondi = t.closest('[data-rispondi]');
    if (rispondi && msg && modulo) impostaRisposta(msg);
  });

  // ricerca: nella testata solo in questa conversazione, da Ctrl+K in tutte
  document.addEventListener('submit', (ev) => {
    const form = ev.target.closest('[data-cerca-form]');
    if (!form) return;
    ev.preventDefault();
    const q = form.q.value.trim();
    if (q) cercaIn(q, true);
  });
  function cercaIn(q, solo) {
    const p = new URLSearchParams({ q });
    if (canale) p.set('canale', canale);
    if (solo) p.set('solo', '1');
    pannello.dataset.url = ''; apriPannello(`${app.dataset.cerca}?${p}`);
  }
  if (app.dataset.cercaIniziale) cercaIn(app.dataset.cercaIniziale, false);

  // --- scrittura ---
  const modulo = document.querySelector('[data-scrivi]');
  if (!modulo) return;
  const area = modulo.querySelector('[data-area]');
  const file = modulo.querySelector('[data-file]');
  const scelti = modulo.querySelector('[data-scelti]');
  const rispostaInput = modulo.querySelector('[data-risposta]');
  const rispostaFascia = modulo.querySelector('[data-rispondi-a]');
  const suggerimenti = modulo.querySelector('[data-suggerimenti]');
  const chiaveBozza = `ds-bozza-${canale}`;

  function cresci() { area.style.height = 'auto'; area.style.height = `${Math.min(area.scrollHeight, 220)}px`; }
  try { const b = localStorage.getItem(chiaveBozza); if (b) { area.value = b; cresci(); } } catch (e) { /* niente bozze */ }

  function impostaRisposta(msg) {
    rispostaInput.value = msg.dataset.id;
    const testo = (msg.querySelector('.ds-testo') || {}).textContent || 'file allegato';
    rispostaFascia.querySelector('span').textContent = `Rispondi a ${msg.dataset.autore}: ${testo.trim().slice(0, 90)}`;
    rispostaFascia.hidden = false;
    area.focus();
  }
  function togliRisposta() { rispostaInput.value = ''; rispostaFascia.hidden = true; }
  modulo.addEventListener('click', (ev) => { if (ev.target.closest('[data-annulla-risposta]')) togliRisposta(); });

  // file: elenco a chip, incolla e trascina
  function disegnaFile() {
    scelti.textContent = '';
    scelti.hidden = !file.files.length;
    Array.from(file.files).forEach((f, i) => {
      const c = document.createElement('span'); c.className = 'ds-scelto'; c.textContent = f.name;
      const x = document.createElement('button'); x.type = 'button'; x.textContent = '×'; x.setAttribute('aria-label', `Togli ${f.name}`);
      x.addEventListener('click', () => {
        const d = new DataTransfer();
        Array.from(file.files).forEach((g, k) => { if (k !== i) d.items.add(g); });
        file.files = d.files; disegnaFile();
      });
      c.appendChild(x); scelti.appendChild(c);
    });
  }
  function aggiungiFile(elenco) {
    const d = new DataTransfer();
    Array.from(file.files).forEach((f) => d.items.add(f));
    Array.from(elenco).forEach((f) => d.items.add(f));
    file.files = d.files; disegnaFile();
  }
  file.addEventListener('change', disegnaFile);
  area.addEventListener('paste', (ev) => { if (ev.clipboardData.files.length) { ev.preventDefault(); aggiungiFile(ev.clipboardData.files); } });
  const conversazione = modulo.closest('.ds-conversazione');
  ['dragenter', 'dragover'].forEach((n) => conversazione.addEventListener(n, (ev) => { if (ev.dataTransfer.types.includes('Files')) { ev.preventDefault(); conversazione.classList.add('is-trascina'); } }));
  conversazione.addEventListener('dragleave', (ev) => { if (!conversazione.contains(ev.relatedTarget)) conversazione.classList.remove('is-trascina'); });
  conversazione.addEventListener('drop', (ev) => { conversazione.classList.remove('is-trascina'); if (ev.dataTransfer.files.length) { ev.preventDefault(); aggiungiFile(ev.dataTransfer.files); } });

  // forme, @ e emoji
  function inserisci(prima, dopo = '') {
    const a = area.selectionStart, b = area.selectionEnd, v = area.value;
    area.value = v.slice(0, a) + prima + v.slice(a, b) + dopo + v.slice(b);
    area.selectionStart = a + prima.length; area.selectionEnd = b + prima.length;
    area.focus(); cresci();
    area.dispatchEvent(new Event('input', { bubbles: true }));
  }
  modulo.addEventListener('click', (ev) => {
    const forma = ev.target.closest('[data-forma]');
    if (forma) { inserisci(forma.dataset.forma, forma.dataset.forma); return; }
    const ins = ev.target.closest('[data-inserisci]');
    if (ins) { inserisci(ins.dataset.inserisci); return; }
    const em = ev.target.closest('[data-emoji-testo]');
    if (em) apriEmoji(em, (e) => inserisci(e));
  });

  // completamento di @persona e #canale
  let voci = [], scelta = 0, attesa, attiva = null;
  function chiudiSuggerimenti() { suggerimenti.hidden = true; voci = []; attiva = null; }
  function disegnaSuggerimenti() {
    suggerimenti.textContent = '';
    voci.forEach((v, i) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'ds-suggerimento' + (i === scelta ? ' is-scelto' : ''); b.setAttribute('role', 'option');
      if (v.stato) { const p = document.createElement('span'); p.className = `ds-punto-testo is-${v.stato}`; b.appendChild(p); }
      const t = document.createElement('span'); t.textContent = v.testo; b.appendChild(t);
      if (v.dettaglio) { const d = document.createElement('small'); d.textContent = v.dettaglio; b.appendChild(d); }
      b.addEventListener('mousedown', (ev) => { ev.preventDefault(); applica(v); });
      suggerimenti.appendChild(b);
    });
    suggerimenti.hidden = !voci.length;
  }
  function applica(v) {
    const a = area.selectionStart, inizio = attiva.inizio;
    const prefisso = attiva.segno;
    area.value = `${area.value.slice(0, inizio)}${prefisso}${v.valore} ${area.value.slice(a)}`;
    area.selectionStart = area.selectionEnd = inizio + prefisso.length + v.valore.length + 1;
    chiudiSuggerimenti(); area.focus(); cresci();
  }
  function controllaParola() {
    const prima = area.value.slice(0, area.selectionStart);
    const m = prima.match(/(?:^|\s)([@#])([\w.+-]*)$/);
    if (!m) { chiudiSuggerimenti(); return; }
    attiva = { segno: m[1], inizio: prima.length - m[2].length - 1 };
    clearTimeout(attesa);
    attesa = setTimeout(async () => {
      const p = new URLSearchParams({ q: m[2], tipo: m[1] === '#' ? 'canali' : 'persone' });
      try {
        const r = await fetch(`${app.dataset.suggerisci}?${p}`);
        if (!r.ok || !attiva) return;
        voci = (await r.json()).voci; scelta = 0; disegnaSuggerimenti();
      } catch (e) { /* senza rete nessun suggerimento */ }
    }, 120);
  }

  let ultimoScrivo = 0;
  area.addEventListener('input', () => {
    cresci(); controllaParola();
    try { if (area.value) localStorage.setItem(chiaveBozza, area.value); else localStorage.removeItem(chiaveBozza); } catch (e) { /* niente bozze */ }
    if (area.value && Date.now() - ultimoScrivo > 3000) { ultimoScrivo = Date.now(); post(app.dataset.scrivo).catch(() => {}); }
  });
  area.addEventListener('keydown', (ev) => {
    if (!suggerimenti.hidden && voci.length) {
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); scelta = (scelta + (ev.key === 'ArrowDown' ? 1 : -1) + voci.length) % voci.length; disegnaSuggerimenti(); return; }
      if (ev.key === 'Enter' || ev.key === 'Tab') { ev.preventDefault(); applica(voci[scelta]); return; }
      if (ev.key === 'Escape') { chiudiSuggerimenti(); return; }
    }
    if (ev.key === 'Escape' && rispostaInput.value) { togliRisposta(); return; }
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      if (area.value.trim() || file.files.length) modulo.requestSubmit();
    }
    if (ev.key === 'ArrowUp' && !area.value) {           // freccia su: modifica l'ultimo messaggio mio
      const miei = lista.querySelectorAll('.ds-messaggio.is-mio');
      const ultimo = miei[miei.length - 1];
      const bottone = ultimo && ultimo.querySelector('[hx-get*="modifica"]');
      if (bottone) { ev.preventDefault(); bottone.click(); }
    }
  });
  modulo.addEventListener('htmx:afterRequest', (ev) => {
    if (ev.detail.elt !== modulo) return;
    if (ev.detail.successful) {
      modulo.reset(); disegnaFile(); togliRisposta(); chiudiSuggerimenti(); cresci();
      try { localStorage.removeItem(chiaveBozza); } catch (e) { /* niente bozze */ }
      eraInFondo = true;
      area.focus();
    } else if (ev.detail.xhr && ev.detail.xhr.status === 422) {
      avvisa(ev.detail.xhr.responseText);
    }
  });

  // messaggi vocali: il browser concede il microfono solo su HTTPS
  const vocale = modulo.querySelector('[data-vocale]');
  const pannelloRec = modulo.querySelector('[data-registra]');
  const tempoRec = modulo.querySelector('[data-registra-tempo]');
  let registratore, pezzi, inizioRec, orologio, flussoRec, daInviare;
  function fermaRec() {
    clearInterval(orologio);
    if (flussoRec) flussoRec.getTracks().forEach((t) => t.stop());
    pannelloRec.hidden = true; vocale.hidden = false;
  }
  if (vocale) vocale.addEventListener('click', async () => {
    if (!window.isSecureContext || !navigator.mediaDevices || !window.MediaRecorder) {
      avvisa('Il browser permette il microfono solo su una connessione sicura (HTTPS): i vocali funzionano quando il sito è in HTTPS.');
      return;
    }
    try { flussoRec = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { avvisa('Microfono non disponibile o non autorizzato.'); return; }
    const tipo = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find((t) => MediaRecorder.isTypeSupported(t)) || '';
    registratore = new MediaRecorder(flussoRec, tipo ? { mimeType: tipo } : {});
    pezzi = []; daInviare = false;
    registratore.ondataavailable = (e) => { if (e.data.size) pezzi.push(e.data); };
    registratore.onstop = () => {
      fermaRec();
      if (!daInviare || !pezzi.length) return;
      const est = (registratore.mimeType || '').includes('mp4') ? 'm4a' : (registratore.mimeType || '').includes('ogg') ? 'ogg' : 'webm';
      aggiungiFile([new File(pezzi, `messaggio-vocale-${Date.now()}.${est}`, { type: registratore.mimeType })]);
      modulo.requestSubmit();
    };
    registratore.start();
    inizioRec = Date.now(); tempoRec.textContent = '0:00'; pannelloRec.hidden = false; vocale.hidden = true;
    orologio = setInterval(() => { const s = Math.floor((Date.now() - inizioRec) / 1000); tempoRec.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }, 500);
  });
  modulo.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-registra-annulla]')) { daInviare = false; registratore.stop(); }
    if (ev.target.closest('[data-registra-invia]')) { daInviare = true; registratore.stop(); }
  });
  if (!app.dataset.bersaglio && !location.hash) area.focus();
})();
