/* «Le mie previsioni»: cerca per parole (titolo, etichetta, argomento: il data-cerca di ogni riga) e filtra per
   argomento, tipo, origine ed etichetta e, con «Solo salvate», le sole salvate. Più parole: servono tutte; accenti e maiuscole non contano. I filtri restano
   nell'indirizzo (?q=&argomento=&tipo=&origine=&etichetta=&salvate=1), come nella pagina Applicazioni. */
(function () {
  'use strict';
  const barra = document.getElementById('prev-barra');
  if (!barra) return;
  const cerca = document.getElementById('prev-cerca'), vuoto = document.getElementById('prev-vuoto');
  const tendine = [...barra.querySelectorAll('select[data-filtro]')];
  const corpo = document.getElementById('prev-mie-righe'), salvate = document.getElementById('prev-salvate');
  const datalist = document.getElementById('prev-etichette');
  const piano = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

  const filtra = () => {
    const parole = piano(cerca.value).split(/\s+/).filter(Boolean);
    const scelti = tendine.map((t) => [t.dataset.filtro, piano(t.value)]).filter(([, v]) => v);
    const righe = [...corpo.querySelectorAll('tr[data-cerca]')];
    let viste = 0;
    righe.forEach((r) => {
      const testo = piano(r.dataset.cerca);
      const si = parole.every((p) => testo.includes(p)) && (!salvate.checked || r.dataset.salvata === 'si') && scelti.every(([k, v]) => piano(r.dataset[k]) === v);
      r.hidden = !si;
      viste += si ? 1 : 0;
    });
    vuoto.hidden = (parole.length === 0 && scelti.length === 0 && !salvate.checked) || viste > 0;
    const url = new URL(window.location.href);
    [['q', cerca.value.trim()], ['salvate', salvate.checked ? '1' : ''], ...tendine.map((t) => [t.dataset.filtro, t.value])].forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v); else url.searchParams.delete(k);
    });
    window.history.replaceState(window.history.state, '', url);
  };

  cerca.addEventListener('input', filtra);
  tendine.forEach((t) => t.addEventListener('change', filtra));
  salvate.addEventListener('change', filtra);
  document.getElementById('prev-azzera').addEventListener('click', () => {
    cerca.value = '';
    tendine.forEach((t) => { t.value = ''; });
    salvate.checked = false;
    filtra();
    cerca.focus();
  });
  // le etichette presenti nelle righe: la tendina del filtro e l'elenco dei suggerimenti si aggiornano senza ricaricare
  const aggiornaEtichette = () => {
    const tendina = tendine.find((t) => t.dataset.filtro === 'etichetta');
    const nomi = [...new Set([...corpo.querySelectorAll('tr[data-cerca]')].map((r) => r.dataset.etichetta).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, 'it', { sensitivity: 'base' }));
    const scelta = tendina.value;
    const opzione = (testo, valore) => { const o = document.createElement('option'); o.value = valore; o.textContent = testo; return o; };
    tendina.replaceChildren(opzione('Tutte le etichette', ''), ...nomi.map((n) => opzione(n, n)));
    tendina.value = nomi.includes(scelta) ? scelta : '';
    tendina.hidden = nomi.length === 0;
    datalist.replaceChildren(...nomi.map((n) => { const o = document.createElement('option'); o.value = n; return o; }));
  };
  // una riga rinominata o rietichettata (HTMX) rientra nei filtri di adesso
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (e.target.id !== 'prev-mie-righe' && !e.target.closest('#prev-mie-righe')) return;
    aggiornaEtichette();
    filtra();
  });
  // una richiesta rifiutata (400: titolo vuoto o troppo lungo, etichetta troppo lunga) si dice nella riga
  const messaggio = (form, testo) => { const m = form && form.querySelector('.prev-errore'); if (m) { m.textContent = testo; m.hidden = !testo; } };
  document.body.addEventListener('htmx:responseError', (e) => {
    const form = e.detail.elt && e.detail.elt.closest ? e.detail.elt.closest('#prev-mie-righe form') : null;
    if (!form) return;
    const stato = e.detail.xhr ? e.detail.xhr.status : 0;
    messaggio(form, stato === 400 ? ((e.detail.xhr.responseText || '').trim() || 'Valore non valido.') : 'Non è stato possibile salvare (' + stato + ').');
  });
  document.body.addEventListener('htmx:beforeRequest', (e) => messaggio(e.detail.elt && e.detail.elt.closest ? e.detail.elt.closest('#prev-mie-righe form') : null, ''));

  // all'apertura: i filtri dell'indirizzo, se i valori ci sono ancora
  const da = new URLSearchParams(window.location.search);
  cerca.value = da.get('q') || '';
  tendine.forEach((t) => { if ([...t.options].some((o) => o.value && o.value === da.get(t.dataset.filtro))) t.value = da.get(t.dataset.filtro); });
  salvate.checked = da.get('salvate') === '1';
  if (cerca.value || salvate.checked || tendine.some((t) => t.value)) filtra();
})();
