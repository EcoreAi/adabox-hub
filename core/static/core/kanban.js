// Kanban: la card segue il mouse e al rilascio la colonna si trova dalla posizione; POST al server, card rimessa a posto se rifiutato.
// Niente drag & drop nativo: il rilascio non dipende dalle regole del browser. Al tocco lo schermo resta libero di scorrere.
// Ogni colonna scorre per conto suo e carica le altre card scendendo; le scelte (ripiegate, compatta, ordine) restano nel browser.
(function () {
  const tabellone = document.querySelector('.ui-kanban');
  if (!tabellone) return;
  const csrf = (document.querySelector('input[name=csrfmiddlewaretoken]') || {}).value;
  const SOGLIA = 5, BORDO = 60, PASSO = 14;
  const CHIAVE = `kanban:${location.pathname}`;
  let presa = null;

  // --- scelte che restano ---
  const leggi = () => { try { return JSON.parse(localStorage.getItem(CHIAVE)) || {}; } catch (e) { return {}; } };
  const scrivi = (dati) => { try { localStorage.setItem(CHIAVE, JSON.stringify({ ...leggi(), ...dati })); } catch (e) { /* si perde alla chiusura */ } };
  const colonneTutte = () => [...tabellone.querySelectorAll('.ui-kanban-col')];

  // --- il tabellone sta nello schermo ---
  const adatta = () => {
    const alto = window.innerHeight - tabellone.getBoundingClientRect().top - window.scrollY - 16;
    tabellone.style.setProperty('--kanban-alto', `${Math.max(380, alto)}px`);
  };
  adatta();
  window.addEventListener('resize', adatta);

  // --- caricare e ordinare ---
  const query = (extra) => {
    const q = new URLSearchParams(location.search);
    Object.entries(extra).forEach(([k, v]) => q.set(k, v));
    return `${location.pathname}?${q}`;
  };
  const altriLink = (col, n) => {
    let a = col.querySelector('.ui-kanban-altri');
    if (!a && n > 0) return null;
    if (a) { a.hidden = n <= 0; if (n > 0) a.textContent = `Altre ${n}`; }
    return a;
  };
  const carica = async (col, azzera, mostra) => {
    if (col.dataset.inCorso) return;
    if (!azzera && parseInt(col.dataset.altri, 10) <= 0) return;
    col.dataset.inCorso = '1';
    try {
      const ordine = col.querySelector('[data-ordina]').value;
      const r = await fetch(query({ colonna: col.dataset.valore, da: azzera ? 0 : col.dataset.caricate, ordine }), { credentials: 'same-origin' });
      if (!r.ok) return;
      const lista = col.querySelector('.ui-kanban-card-list');
      const pezzo = document.createElement('div');
      pezzo.innerHTML = await r.text();
      const nuove = [...pezzo.children];
      if (azzera) { lista.replaceChildren(...nuove); lista.scrollTop = 0; col.dataset.caricate = nuove.length; } else {
        lista.append(...nuove); col.dataset.caricate = parseInt(col.dataset.caricate, 10) + nuove.length;
      }
      col.dataset.altri = r.headers.get('X-Altri') || '0';
      altriLink(col, parseInt(col.dataset.altri, 10));
      if (mostra && nuove.length) lista.scrollTo({ top: nuove[0].offsetTop - lista.offsetTop - 8, behavior: 'smooth' });   // col clic si vedono subito
      applicaTrova();
    } finally { delete col.dataset.inCorso; }
  };
  tabellone.querySelectorAll('.ui-kanban-card-list').forEach((lista) => lista.addEventListener('scroll', () => {
    if (lista.scrollTop + lista.clientHeight > lista.scrollHeight - 200) carica(lista.closest('.ui-kanban-col'));
  }, { passive: true }));

  // --- le scelte salvate ---
  const scelte = leggi();
  colonneTutte().forEach((col) => {
    const v = col.dataset.valore;
    if (scelte.ripiegate && v in scelte.ripiegate) col.classList.toggle('is-ripiegata', scelte.ripiegate[v]);
    const sel = col.querySelector('[data-ordina]');
    const ordine = scelte.ordini && scelte.ordini[v];
    if (ordine && [...sel.options].some((o) => o.value === ordine)) { sel.value = ordine; carica(col, true); }
    sel.addEventListener('change', () => {
      scrivi({ ordini: { ...(leggi().ordini || {}), [v]: sel.value } });
      carica(col, true);
    });
  });
  const compatta = document.getElementById('kb-compatta');
  compatta.checked = !!scelte.compatta;
  tabellone.classList.toggle('is-compatta', compatta.checked);
  compatta.addEventListener('change', () => { tabellone.classList.toggle('is-compatta', compatta.checked); scrivi({ compatta: compatta.checked }); });

  tabellone.addEventListener('click', (e) => {
    const altri = e.target.closest('.ui-kanban-altri');
    if (altri) {
      e.preventDefault();
      const col = altri.closest('.ui-kanban-col'), lista = col.querySelector('.ui-kanban-card-list');
      if (parseInt(col.dataset.altri, 10) > 0) carica(col, false, true);
      else lista.scrollTo({ top: lista.scrollHeight, behavior: 'smooth' });
      return;
    }
    const col = e.target.closest('.ui-kanban-col');
    if (!col) return;
    if (e.target.closest('[data-ripiega]') || col.classList.contains('is-ripiegata')) {
      const ripiegata = col.classList.toggle('is-ripiegata');
      scrivi({ ripiegate: { ...(leggi().ripiegate || {}), [col.dataset.valore]: ripiegata } });
    }
  });

  // --- trova una scheda tra quelle caricate ---
  const trova = document.getElementById('kb-trova'), trovate = document.getElementById('kb-trovate');
  let trovateOra = [], indice = -1;
  function applicaTrova() {
    const testo = trova.value.trim().toLowerCase();
    trovateOra = [];
    tabellone.querySelectorAll('.ui-kanban-card').forEach((c) => {
      const si = !!testo && c.textContent.toLowerCase().includes(testo);
      c.classList.toggle('is-trovata', si);
      c.classList.toggle('is-sfumata', !!testo && !si);
      if (si) trovateOra.push(c);
    });
    trovate.textContent = testo ? `${trovateOra.length} tra le schede caricate${trovateOra.length ? ' · Invio per la prossima' : ' · per cercarle tutte usa «Cerca» qui sopra'}` : '';
  }
  const vaiA = (passo) => {
    if (!trovateOra.length) return;
    indice = (indice + passo + trovateOra.length) % trovateOra.length;
    const c = trovateOra[indice], col = c.closest('.ui-kanban-col');
    col.classList.remove('is-ripiegata');
    c.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
  };
  trova.addEventListener('input', () => { indice = -1; applicaTrova(); vaiA(1); });
  trova.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); vaiA(e.shiftKey ? -1 : 1); } });

  // --- dopo uno spostamento ---
  const aggiorna = (col, delta) => {
    const n = col.querySelector('[data-conteggio]');
    if (n) n.textContent = String(parseInt(n.textContent, 10) + delta);
  };

  // Spostare cambia ciò che la card mostra e i totali delle colonne: si riprendono solo quelli, senza perdere lo scorrimento.
  const ridisegna = async (card) => {
    try {
      const [c, t] = await Promise.all([fetch(query({ card: card.dataset.pk }), { credentials: 'same-origin' }), fetch(location.href, { credentials: 'same-origin' })]);
      if (c.ok) { const pezzo = document.createElement('div'); pezzo.innerHTML = await c.text(); if (pezzo.firstElementChild) card.replaceWith(pezzo.firstElementChild); }
      if (t.ok) {
        const nuovo = new DOMParser().parseFromString(await t.text(), 'text/html');
        colonneTutte().forEach((col) => {
          const altra = [...nuovo.querySelectorAll('.ui-kanban-col')].find((x) => x.dataset.valore === col.dataset.valore);
          if (!altra) return;
          col.querySelector('[data-conteggio]').textContent = altra.querySelector('[data-conteggio]').textContent;
          const r = col.querySelector('[data-riepilogo]'), s = altra.querySelector('[data-riepilogo]');
          if (r && s) { r.textContent = s.textContent; r.hidden = s.hidden; }
        });
      }
      applicaTrova();
    } catch (errore) { /* resta la vista di prima: lo spostamento è comunque salvato */ }
  };

  // Dopo il rilascio: un avviso discreto con «Aggiungi una nota». Se non serve, sparisce da solo.
  let avviso = null, chiusura = null;
  const togliAvviso = () => { clearTimeout(chiusura); if (avviso) avviso.remove(); avviso = null; };
  const mostraAvviso = (card, col, urlNota) => {
    togliAvviso();
    avviso = document.createElement('div');
    avviso.className = 'ui-kanban-avviso';
    avviso.setAttribute('role', 'status');
    const testo = document.createElement('span');
    testo.textContent = `Spostata in ${col.querySelector('.ui-kanban-col-nome').textContent}.`;
    const bottone = document.createElement('button');
    bottone.type = 'button'; bottone.className = 'ui-btn ui-btn-secondary ui-btn-sm'; bottone.textContent = 'Aggiungi una nota';
    const chiudi = document.createElement('button');
    chiudi.type = 'button'; chiudi.className = 'ui-btn ui-btn-ghost ui-btn-sm'; chiudi.textContent = '×'; chiudi.setAttribute('aria-label', 'Chiudi');
    chiudi.addEventListener('click', togliAvviso);
    bottone.addEventListener('click', () => {
      clearTimeout(chiusura);
      const area = document.createElement('textarea');
      area.className = 'ui-input'; area.maxLength = 2000; area.placeholder = 'Perché l\'hai spostata?'; area.setAttribute('aria-label', 'Nota allo spostamento');
      const salva = document.createElement('button');
      salva.type = 'button'; salva.className = 'ui-btn ui-btn-primary ui-btn-sm'; salva.textContent = 'Salva la nota';
      salva.addEventListener('click', async () => {
        if (!area.value.trim()) { area.focus(); return; }
        const dati = new FormData();
        dati.append('nota', area.value);
        const r = await fetch(urlNota, { method: 'POST', body: dati, headers: { 'X-CSRFToken': csrf }, credentials: 'same-origin' }).catch(() => null);
        if (!r || !r.ok) { if (window.uiToast) window.uiToast('Nota non salvata', 'warn'); return; }
        togliAvviso();
        const attuale = tabellone.querySelector(`.ui-kanban-card[data-pk="${card.dataset.pk}"]`);
        if (attuale) ridisegna(attuale);
      });
      bottone.replaceWith(salva);
      avviso.prepend(area);
      area.focus();
    });
    avviso.append(testo, bottone, chiudi);
    document.body.append(avviso);
    chiusura = setTimeout(togliAvviso, 8000);
  };

  const sposta = async (card, origine, col) => {
    col.querySelector('.ui-kanban-card-list').prepend(card);
    aggiorna(origine, -1); aggiorna(col, +1);
    const dati = new FormData();
    dati.append('valore', col.dataset.valore);
    try {
      const r = await fetch(card.dataset.sposta, {method: 'POST', body: dati,
        headers: {'X-CSRFToken': csrf, 'HX-Request': 'true'}, credentials: 'same-origin'});
      if (!r.ok) throw new Error(r.status === 409 ? await r.text() : 'Spostamento non riuscito');
      const urlNota = r.headers.get('X-Nota');
      if (urlNota) mostraAvviso(card, col, urlNota);
      ridisegna(card);
    } catch (errore) {
      origine.querySelector('.ui-kanban-card-list').prepend(card);
      aggiorna(origine, +1); aggiorna(col, -1);
      if (window.uiToast) window.uiToast(errore.message || 'Spostamento non riuscito', 'warn');
    }
  };

  // Conta la posizione orizzontale: una colonna con poche card è bassa, ma sotto di lei si sta ancora puntando a lei.
  const colonnaSotto = (x, y) => {
    const t = tabellone.getBoundingClientRect();
    if (y < t.top || x < t.left || x > t.right) return null;
    let vicina = null, minima = Infinity;
    tabellone.querySelectorAll('.ui-kanban-col').forEach((col) => {
      const r = col.getBoundingClientRect();
      const distanza = x < r.left ? r.left - x : x > r.right ? x - r.right : 0;
      if (distanza < minima) { minima = distanza; vicina = col; }
    });
    return vicina;
  };

  const evidenzia = (col) => {
    tabellone.querySelectorAll('.is-sopra').forEach((c) => c !== col && c.classList.remove('is-sopra'));
    if (col) col.classList.add('is-sopra');
  };

  const inizia = (e) => {
    const r = presa.card.getBoundingClientRect();
    presa.dx = presa.x - r.left; presa.dy = presa.y - r.top;
    presa.volante = presa.card.cloneNode(true);
    presa.volante.classList.add('is-volante');
    // In linea: le regole del tabellone (position: relative sulle card) non devono rimetterla in fila dopo l'ultima colonna.
    Object.assign(presa.volante.style, {position: 'fixed', left: '0', top: '0', margin: '0', width: `${r.width}px`});
    tabellone.append(presa.volante);         // dentro il tabellone, così tiene gli stili della card
    presa.card.classList.add('is-trascinata');
    document.body.classList.add('is-trascinando');
    muovi(e);
  };

  const muovi = (e) => {
    if (!presa) return;
    if (!presa.volante) {
      if (Math.hypot(e.clientX - presa.x, e.clientY - presa.y) >= SOGLIA) inizia(e);
      return;
    }
    e.preventDefault();
    presa.volante.style.transform = `translate(${e.clientX - presa.dx}px, ${e.clientY - presa.dy}px) rotate(1.5deg)`;
    const r = tabellone.getBoundingClientRect();           // le colonne fuori schermo si raggiungono avvicinandosi al bordo
    if (e.clientX > r.right - BORDO) tabellone.scrollLeft += PASSO;
    else if (e.clientX < r.left + BORDO) tabellone.scrollLeft -= PASSO;
    const col = colonnaSotto(e.clientX, e.clientY);
    evidenzia(col);
    const lista = col && col.querySelector('.ui-kanban-card-list');
    if (lista && lista.clientHeight) {                     // e dentro una colonna lunga si scorre avvicinandosi ai suoi bordi
      const l = lista.getBoundingClientRect();
      if (e.clientY > l.bottom - BORDO) lista.scrollTop += PASSO;
      else if (e.clientY < l.top + BORDO) lista.scrollTop -= PASSO;
    }
  };

  const fine = (e, rilascia) => {
    if (!presa) return;
    const {card, volante, origine} = presa;
    presa = null;
    document.removeEventListener('pointermove', muovi);
    document.removeEventListener('pointerup', suRilascio);
    document.removeEventListener('pointercancel', suAnnullo);
    document.removeEventListener('keydown', suTasto);
    if (!volante) return;
    const col = rilascia ? colonnaSotto(e.clientX, e.clientY) : null;
    volante.remove();
    card.classList.remove('is-trascinata');
    document.body.classList.remove('is-trascinando');
    evidenzia(null);
    // Il rilascio sopra il titolo non deve aprire la scheda: il clic subito dopo non conta.
    const ignora = (c) => { c.preventDefault(); c.stopPropagation(); };
    document.addEventListener('click', ignora, {capture: true, once: true});
    setTimeout(() => document.removeEventListener('click', ignora, {capture: true}), 0);
    if (col && col !== origine) sposta(card, origine, col);
  };
  const suRilascio = (e) => fine(e, true);
  const suAnnullo = (e) => fine(e, false);
  const suTasto = (e) => { if (e.key === 'Escape') fine(e, false); };

  tabellone.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || e.pointerType === 'touch' || presa) return;
    const card = e.target.closest('.ui-kanban-card[data-trascinabile]');
    if (!card || e.target.closest('input, select, button, textarea')) return;
    presa = {card, origine: card.closest('.ui-kanban-col'), x: e.clientX, y: e.clientY, volante: null};
    document.addEventListener('pointermove', muovi);
    document.addEventListener('pointerup', suRilascio);
    document.addEventListener('pointercancel', suAnnullo);
    document.addEventListener('keydown', suTasto);
  });
  // Titoli e testi non partono col trascinamento nativo del browser.
  tabellone.addEventListener('dragstart', (e) => e.preventDefault());
})();
