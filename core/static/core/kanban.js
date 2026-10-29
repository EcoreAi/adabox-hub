// Kanban: drag & drop HTML5 nativo tra le colonne; POST al server, card rimessa a posto se rifiutato.
(function () {
  const tabellone = document.querySelector('.ui-kanban');
  if (!tabellone) return;
  const csrf = (document.querySelector('input[name=csrfmiddlewaretoken]') || {}).value;
  let trascinata = null;

  const aggiorna = (col, delta) => {
    const n = col.querySelector('[data-conteggio]');
    if (n) n.textContent = String(parseInt(n.textContent, 10) + delta);
  };

  tabellone.addEventListener('dragstart', (e) => {
    trascinata = e.target.closest('.ui-kanban-card');
    if (!trascinata) return;
    e.dataTransfer.effectAllowed = 'move';
    trascinata.classList.add('is-trascinata');
  });
  tabellone.addEventListener('dragend', () => {
    if (trascinata) trascinata.classList.remove('is-trascinata');
    tabellone.querySelectorAll('.is-sopra').forEach((c) => c.classList.remove('is-sopra'));
  });
  tabellone.addEventListener('dragover', (e) => {
    const col = e.target.closest('.ui-kanban-col');
    if (!col || !trascinata) return;
    e.preventDefault();
    tabellone.querySelectorAll('.is-sopra').forEach((c) => c !== col && c.classList.remove('is-sopra'));
    col.classList.add('is-sopra');
  });
  tabellone.addEventListener('drop', async (e) => {
    const col = e.target.closest('.ui-kanban-col');
    if (!col || !trascinata) return;
    e.preventDefault();
    const card = trascinata;
    const origine = card.closest('.ui-kanban-col');
    if (origine === col) return;
    col.querySelector('.ui-kanban-card-list').prepend(card);
    aggiorna(origine, -1); aggiorna(col, +1);
    const dati = new FormData();
    dati.append('valore', col.dataset.valore);
    try {
      const r = await fetch(card.dataset.sposta, {method: 'POST', body: dati,
        headers: {'X-CSRFToken': csrf, 'HX-Request': 'true'}, credentials: 'same-origin'});
      if (!r.ok) throw new Error(r.status === 409 ? await r.text() : 'Spostamento non riuscito');
    } catch (errore) {
      origine.querySelector('.ui-kanban-card-list').prepend(card);
      aggiorna(origine, +1); aggiorna(col, -1);
      if (window.uiToast) window.uiToast(errore.message || 'Spostamento non riuscito', 'warn');
    }
  });
})();
