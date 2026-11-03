// Kanban: la card segue il mouse e al rilascio la colonna si trova dalla posizione; POST al server, card rimessa a posto se rifiutato.
// Niente drag & drop nativo: il rilascio non dipende dalle regole del browser. Al tocco lo schermo resta libero di scorrere.
(function () {
  const tabellone = document.querySelector('.ui-kanban');
  if (!tabellone) return;
  const csrf = (document.querySelector('input[name=csrfmiddlewaretoken]') || {}).value;
  const SOGLIA = 5, BORDO = 60, PASSO = 14;
  let presa = null;

  const aggiorna = (col, delta) => {
    const n = col.querySelector('[data-conteggio]');
    if (n) n.textContent = String(parseInt(n.textContent, 10) + delta);
  };

  // Spostare può cambiare ciò che la card mostra (probabilità, totali della colonna): si riprende il tabellone dal server.
  const ricarica = async () => {
    try {
      const r = await fetch(location.href, {credentials: 'same-origin'});
      if (!r.ok) return;
      const nuovo = new DOMParser().parseFromString(await r.text(), 'text/html').querySelector('.ui-kanban');
      if (nuovo) tabellone.replaceChildren(...nuovo.childNodes);
    } catch (errore) { /* resta la vista di prima: lo spostamento è comunque salvato */ }
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
      if ('ricarica' in tabellone.dataset) ricarica();
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
    evidenzia(colonnaSotto(e.clientX, e.clientY));
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
