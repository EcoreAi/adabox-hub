/* Pagina Applicazioni: cerca per parole (nome, categoria, descrizione, funzioni: il data-cerca di ogni scheda) e filtra
   per stato e categoria, in tutte le sezioni. Più parole: servono tutte; accenti e maiuscole non contano. Le sezioni
   senza app che corrispondono spariscono. I filtri restano nell'indirizzo (?q=&stato=&categoria=): tornando indietro
   da una scheda si ritrovano. */
(function () {
  'use strict';
  const barra = document.getElementById('mk-barra');
  if (!barra) return;
  const cerca = document.getElementById('mk-cerca'), categoria = document.getElementById('mk-categoria');
  const vuoto = document.getElementById('mk-vuoto'), sezioni = document.querySelectorAll('.mk-sezione');
  const chip = barra.querySelectorAll('[data-stato]');
  const piano = (t) => (t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  let stato = '';

  const scegliStato = (valore) => {
    stato = valore;
    chip.forEach((c) => { const si = c.dataset.stato === valore; c.classList.toggle('is-attiva', si); c.setAttribute('aria-pressed', si); });
  };

  const filtra = () => {
    const parole = piano(cerca.value).split(/\s+/).filter(Boolean);
    const cat = categoria ? categoria.value : '';
    const filtrando = parole.length > 0 || stato !== '' || cat !== '';
    let viste = 0;
    sezioni.forEach((sezione) => {
      let qui = 0;
      sezione.querySelectorAll('[data-cerca]').forEach((app) => {
        const testo = piano(app.dataset.cerca);
        const si = (!stato || sezione.dataset.gruppo === stato) && (!cat || app.dataset.categoria === cat)
          && parole.every((p) => testo.includes(p));
        app.hidden = !si;
        qui += si ? 1 : 0;
      });
      sezione.hidden = filtrando && qui === 0;
      viste += qui;
    });
    vuoto.hidden = !filtrando || viste > 0;
    const url = new URL(window.location.href);
    [['q', cerca.value.trim()], ['stato', stato], ['categoria', cat]].forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v); else url.searchParams.delete(k);
    });
    window.history.replaceState(window.history.state, '', url);
  };

  cerca.addEventListener('input', filtra);
  if (categoria) categoria.addEventListener('change', filtra);
  barra.addEventListener('click', (e) => {
    const c = e.target.closest('[data-stato]');
    if (!c) return;
    scegliStato(c.dataset.stato);
    filtra();
  });
  document.getElementById('mk-azzera').addEventListener('click', () => {
    cerca.value = '';
    if (categoria) categoria.value = '';
    scegliStato('');
    filtra();
    cerca.focus();
  });

  // all'apertura: i filtri dell'indirizzo, se valgono ancora (uno stato o una categoria che non c'è più si ignora)
  const da = new URLSearchParams(window.location.search);
  cerca.value = da.get('q') || '';
  if ([...chip].some((c) => c.dataset.stato === da.get('stato'))) scegliStato(da.get('stato'));
  if (categoria && [...categoria.options].some((o) => o.value && o.value === da.get('categoria'))) categoria.value = da.get('categoria');
  if (cerca.value || stato || (categoria && categoria.value)) filtra();
})();
