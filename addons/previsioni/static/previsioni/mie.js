/* «Le mie previsioni»: cerca per parole (titolo, etichetta, argomento: il data-cerca di ogni riga) e filtra per
   argomento, tipo, origine ed etichetta. Più parole: servono tutte; accenti e maiuscole non contano. I filtri restano
   nell'indirizzo (?q=&argomento=&tipo=&origine=&etichetta=), come nella pagina Applicazioni. */
(function () {
  'use strict';
  const barra = document.getElementById('prev-barra');
  if (!barra) return;
  const cerca = document.getElementById('prev-cerca'), vuoto = document.getElementById('prev-vuoto');
  const tendine = [...barra.querySelectorAll('select[data-filtro]')];
  const corpo = document.getElementById('prev-mie-righe');
  const piano = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

  const filtra = () => {
    const parole = piano(cerca.value).split(/\s+/).filter(Boolean);
    const scelti = tendine.map((t) => [t.dataset.filtro, piano(t.value)]).filter(([, v]) => v);
    const righe = [...corpo.querySelectorAll('tr[data-cerca]')];
    let viste = 0;
    righe.forEach((r) => {
      const testo = piano(r.dataset.cerca);
      const si = parole.every((p) => testo.includes(p)) && scelti.every(([k, v]) => piano(r.dataset[k]) === v);
      r.hidden = !si;
      viste += si ? 1 : 0;
    });
    vuoto.hidden = (parole.length === 0 && scelti.length === 0) || viste > 0;
    const url = new URL(window.location.href);
    [['q', cerca.value.trim()], ...tendine.map((t) => [t.dataset.filtro, t.value])].forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v); else url.searchParams.delete(k);
    });
    window.history.replaceState(window.history.state, '', url);
  };

  cerca.addEventListener('input', filtra);
  tendine.forEach((t) => t.addEventListener('change', filtra));
  document.getElementById('prev-azzera').addEventListener('click', () => {
    cerca.value = '';
    tendine.forEach((t) => { t.value = ''; });
    filtra();
    cerca.focus();
  });
  // una riga rinominata o rietichettata (HTMX) rientra nei filtri di adesso
  document.body.addEventListener('htmx:afterSwap', (e) => { if (corpo.contains(e.target) || e.target.closest('#prev-mie-righe')) filtra(); });

  // all'apertura: i filtri dell'indirizzo, se i valori ci sono ancora
  const da = new URLSearchParams(window.location.search);
  cerca.value = da.get('q') || '';
  tendine.forEach((t) => { if ([...t.options].some((o) => o.value && o.value === da.get(t.dataset.filtro))) t.value = da.get(t.dataset.filtro); });
  if (cerca.value || tendine.some((t) => t.value)) filtra();
})();
