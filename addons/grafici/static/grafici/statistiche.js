// Pagina Statistiche: ricerca e filtro per tipo nella libreria, le prime 12 righe con «Mostra tutti».
// Senza questo script la libreria resta tutta visibile.
(function () {
  const blocco = document.querySelector('[data-libreria]');
  if (!blocco) return;
  const righe = [...blocco.querySelectorAll('tbody tr')];
  const strumenti = blocco.querySelector('[data-strumenti]');
  const cerca = blocco.querySelector('[data-cerca]');
  const piede = blocco.querySelector('[data-piede]');
  const mostrati = blocco.querySelector('[data-mostrati]');
  const tutti = blocco.querySelector('[data-tutti]');
  const nessuno = blocco.querySelector('[data-nessuno]');
  const segmenti = [...blocco.querySelectorAll('[data-tipo]')].filter((b) => b.tagName === 'BUTTON');
  const PRIMI = 12;
  let tipo = '', testo = '', aperta = false;
  if (!righe.length || !strumenti) return;
  strumenti.hidden = false;

  function disegna() {
    const scelte = righe.filter((r) => (!tipo || r.dataset.tipo === tipo) && (!testo || r.dataset.titolo.includes(testo)));
    righe.forEach((r) => { r.hidden = true; });
    scelte.forEach((r, i) => { r.hidden = !aperta && i >= PRIMI; });
    nessuno.hidden = scelte.length > 0;
    piede.hidden = scelte.length <= PRIMI;
    const visibili = aperta ? scelte.length : Math.min(scelte.length, PRIMI);
    mostrati.textContent = `${visibili} di ${scelte.length}`;
    tutti.textContent = aperta ? 'Mostra meno' : `Mostra tutti i ${scelte.length}`;
  }
  cerca.addEventListener('input', () => { testo = cerca.value.trim().toLowerCase(); disegna(); });
  segmenti.forEach((b) => b.addEventListener('click', () => {
    segmenti.forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    tipo = b.dataset.tipo;
    disegna();
  }));
  tutti.addEventListener('click', () => { aperta = !aperta; disegna(); });
  disegna();
})();
