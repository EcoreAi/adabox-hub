// Chiedi ad Ada: l'etichetta e la finestra escono dalla barra in alto (il suo backdrop-filter le terrebbe dentro) e vanno
// nel body. Alla domanda si allega ciò che c'è sulla pagina: indirizzo, titolo, i dati strutturati (#ada-contesto) e il
// testo visibile. La risposta arriva in diretta con lo stesso flusso della chat.
(function () {
  const etichetta = document.getElementById('ak-etichetta');
  const modale = document.getElementById('ak-modale');
  if (!etichetta || !modale) return;
  [etichetta, modale].forEach((el) => { if (el.parentElement !== document.body) document.body.appendChild(el); });
  const csrf = () => (document.querySelector('input[name=csrfmiddlewaretoken]') || {}).value;

  const pagina = () => {
    const main = document.querySelector('main') || document.body;
    const nodo = document.getElementById('ada-contesto');
    let contesto = nodo ? nodo.textContent.trim() : '';
    let dati = {};
    try { dati = contesto ? JSON.parse(contesto) : {}; } catch (e) { contesto = ''; }
    return { url: location.pathname + location.search, titolo: document.title.replace(/\s·\s.*$/, '').trim(), contesto,
      pagina: (main.innerText || main.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 12000),
      grafici: Array.isArray(dati.grafici) && dati.grafici.length ? '1' : '', kpi: Array.isArray(dati.kpi) && dati.kpi.length ? '1' : '',
      grafico: Array.isArray(dati.dati) ? '1' : '', analisi: typeof dati.pagina === 'string' && dati.pagina.startsWith('Analisi') ? '1' : '' };
  };
  const chiudi = () => { modale.replaceChildren(); };
  const scorri = () => { const t = modale.querySelector('#ak-thread'); if (t) t.scrollTop = t.scrollHeight; };
  const abilita = (si) => { const b = modale.querySelector('[data-ak-invia]'); if (b) b.disabled = !si; };

  const segui = (bolla) => {
    if (!bolla || bolla.dataset.seguita) return;
    bolla.dataset.seguita = '1';
    abilita(false);
    const testo = bolla.querySelector('[data-testo]');
    const avanzamento = bolla.querySelector('[data-avanzamento]');
    const sorgente = new EventSource(bolla.dataset.flusso);
    sorgente.addEventListener('testo', (e) => { testo.textContent += JSON.parse(e.data).delta; scorri(); });
    sorgente.addEventListener('avanzamento', (e) => {
      const voci = JSON.parse(e.data); const ultima = voci[voci.length - 1];
      if (ultima && avanzamento) avanzamento.textContent = ultima.strumento ? `uso «${ultima.strumento}»…` : 'quasi fatto…';
    });
    sorgente.addEventListener('fine', (e) => {
      sorgente.close();
      const dati = JSON.parse(e.data);
      if (dati.html) bolla.outerHTML = dati.html; else bolla.remove();
      abilita(true); scorri();
      const campo = modale.querySelector('textarea'); if (campo) campo.focus();
    });
    sorgente.addEventListener('error', () => {
      if (sorgente.readyState === EventSource.CLOSED && avanzamento) { avanzamento.textContent = 'Connessione persa: la risposta è nella chat.'; abilita(true); }
    });
    const ferma = bolla.querySelector('[data-ferma]');
    if (ferma) ferma.addEventListener('click', () => fetch(bolla.dataset.stop, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, credentials: 'same-origin' }));
  };

  const apri = async () => {
    const p = pagina();
    const q = new URLSearchParams({ url: p.url, titolo: p.titolo, grafici: p.grafici, kpi: p.kpi, grafico: p.grafico, analisi: p.analisi || '' });
    let r;
    try { r = await fetch(`${etichetta.dataset.apri}?${q}`, { credentials: 'same-origin' }); } catch (e) { return; }
    if (!r.ok) return;
    modale.innerHTML = await r.text();
    const form = modale.querySelector('#ak-form');
    form.querySelector('[name=contesto]').value = p.contesto.slice(0, 8000);
    form.querySelector('[name=pagina]').value = p.pagina;
    if (window.htmx) htmx.process(modale);
    const campo = modale.querySelector('textarea');
    campo.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (campo.value.trim() && window.htmx) htmx.trigger(form, 'submit'); } });
    campo.focus();
  };

  etichetta.addEventListener('click', apri);
  modale.addEventListener('click', (e) => {
    if (e.target.closest('[data-ak-chiudi]') || e.target.classList.contains('ak-modale')) { chiudi(); return; }
    const chip = e.target.closest('[data-ak-sugg]');
    if (chip) {
      const form = modale.querySelector('#ak-form');
      form.querySelector('textarea').value = chip.textContent;
      if (window.htmx) htmx.trigger(form, 'submit');
    }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && modale.firstChild) chiudi(); });
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (!e.detail.target || e.detail.target.id !== 'ak-thread') return;
    const sugg = modale.querySelector('.ak-suggerimenti'); if (sugg) sugg.remove();
    const campo = modale.querySelector('textarea'); if (campo) campo.value = '';
    const link = modale.querySelector('[data-ak-link]'); const posto = modale.querySelector('#ak-link-chat');
    if (link && posto) { link.hidden = false; posto.replaceChildren(link); }
    scorri();
    modale.querySelectorAll('[data-flusso]').forEach(segui);
  });
  document.body.addEventListener('htmx:responseError', (e) => {
    if (e.detail.target && e.detail.target.id === 'ak-thread' && window.uiToast) window.uiToast('Non sono riuscito a chiedere ad Ada', 'warn');
  });
})();
