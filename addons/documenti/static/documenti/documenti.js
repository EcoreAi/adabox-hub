// Documenti: selezione per le azioni di massa e caricamento trascinando i file sulla griglia.
(function () {
  const azioni = document.getElementById('doc-azioni');
  if (!azioni) return;
  const barra = azioni.querySelector('[data-barra]');
  const conteggio = azioni.querySelector('[data-conteggio]');
  function aggiorna() {
    const n = azioni.querySelectorAll('input[name="pk"]:checked').length;
    barra.hidden = n === 0;
    conteggio.textContent = n === 1 ? '1 selezionato' : `${n} selezionati`;
  }
  azioni.addEventListener('change', (ev) => { if (ev.target.name === 'pk') aggiorna(); });
  aggiorna();

  const origine = document.querySelector('[data-url-carica]');
  if (!origine) return;
  const csrf = azioni.querySelector('input[name="csrfmiddlewaretoken"]').value;
  let profondita = 0;
  const conFile = (ev) => Array.from(ev.dataTransfer?.types || []).includes('Files');
  azioni.addEventListener('dragenter', (ev) => { if (conFile(ev)) { profondita += 1; azioni.classList.add('is-sopra'); } });
  azioni.addEventListener('dragleave', () => { profondita = Math.max(0, profondita - 1); if (!profondita) azioni.classList.remove('is-sopra'); });
  azioni.addEventListener('dragover', (ev) => { if (conFile(ev)) ev.preventDefault(); });
  azioni.addEventListener('drop', async (ev) => {
    if (!conFile(ev)) return;
    ev.preventDefault();
    profondita = 0;
    azioni.classList.remove('is-sopra');
    const dati = new FormData();
    dati.append('csrfmiddlewaretoken', csrf);
    dati.append('cartella', origine.dataset.cartella);
    Array.from(ev.dataTransfer.files).forEach((f) => dati.append('file', f));
    const risposta = await fetch(origine.dataset.urlCarica, { method: 'POST', body: dati, headers: { Accept: 'application/json' } });
    const esito = await risposta.json().catch(() => ({ errori: ['Caricamento non riuscito.'] }));
    if (esito.errori && esito.errori.length) alert(esito.errori.join('\n'));
    location.reload();
  });
})();
