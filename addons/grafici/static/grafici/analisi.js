// Analisi: «Nuova pagina» tra le schede, cambio di tipo dal menu della card (ridisegna subito e salva), «Chiedi ad
// Ada» con la domanda già scritta, menu che si chiudono cliccando fuori.
(function () {
  const csrf = () => (document.querySelector('input[name=csrfmiddlewaretoken]') || {}).value;

  document.addEventListener('click', (e) => {
    const nuova = e.target.closest('[data-an-nuova]');
    if (nuova) {
      const campo = nuova.parentElement.querySelector('.an-nuova-campo');
      campo.hidden = !campo.hidden;
      nuova.setAttribute('aria-expanded', String(!campo.hidden));
      if (!campo.hidden) campo.querySelector('input').focus();
      return;
    }
    const tipo = e.target.closest('.an-menu-tipi [data-tipo]');
    if (tipo) { cambiaTipo(tipo); return; }
    const ada = e.target.closest('[data-an-ada]');
    if (ada) { chiediAdAda(ada); return; }
    const png = e.target.closest('[data-an-png]');
    if (png) { scaricaPng(png); return; }
    document.querySelectorAll('details.an-menu[open], details.an-salva[open]').forEach((d) => { if (!d.contains(e.target)) d.removeAttribute('open'); });
  });

  async function cambiaTipo(bottone) {
    const box = bottone.closest('.an-menu-tipi');
    const canvas = document.querySelector(`canvas[data-grafico="${box.dataset.tipi}"]`);
    const nodo = document.getElementById(box.dataset.tipi);
    if (!canvas || !nodo || !window.adaboxGrafici) return;
    const serie = JSON.parse(nodo.textContent);
    serie.tipo = bottone.dataset.tipo;
    nodo.textContent = JSON.stringify(serie);
    window.adaboxGrafici.ridisegna(canvas, serie);
    box.querySelectorAll('[data-tipo]').forEach((b) => b.setAttribute('aria-pressed', String(b === bottone)));
    const menu = bottone.closest('details');
    if (menu) menu.removeAttribute('open');
    try {
      const r = await fetch(box.dataset.salva, { method: 'POST', credentials: 'same-origin', body: 'tipo=' + encodeURIComponent(bottone.dataset.tipo),
        headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' } });
      if (!r.ok) throw new Error();
    } catch (err) { if (window.uiToast) window.uiToast('Il tipo non è stato salvato', 'warn'); }
  }

  // il grafico com'è disegnato, in PNG (sfondo pieno: lo mette il plugin del tema)
  function scaricaPng(bottone) {
    const canvas = document.querySelector(`canvas[data-grafico="${bottone.dataset.anPng}"]`);
    const grafico = canvas && window.Chart && Chart.getChart(canvas);
    const menu = bottone.closest('details');
    if (menu) menu.removeAttribute('open');
    if (!grafico) { if (window.uiToast) window.uiToast('Il grafico non è ancora disegnato'); return; }
    const a = document.createElement('a');
    a.href = grafico.toBase64Image('image/png', 1);
    a.download = (bottone.dataset.nome || 'grafico') + '.png';
    document.body.append(a); a.click(); a.remove();
  }

  // askAda, se c'è, apre la sua finestra: la domanda viene scritta appena il modulo è caricato
  function chiediAdAda(bottone) {
    const etichetta = document.getElementById('ak-etichetta');
    if (!etichetta) { if (window.uiToast) window.uiToast('«Chiedi ad Ada» non è attivo'); return; }
    const menu = bottone.closest('details');
    if (menu) menu.removeAttribute('open');
    etichetta.click();
    let tentativi = 0;
    const attesa = setInterval(() => {
      const campo = document.querySelector('#ak-modale [data-testo]');
      if (campo || ++tentativi > 60) {
        clearInterval(attesa);
        if (campo) { campo.value = bottone.dataset.anAda; campo.focus(); campo.dispatchEvent(new Event('input', { bubbles: true })); }
      }
    }, 50);
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('ak-etichetta')) document.querySelectorAll('[data-an-ada]').forEach((b) => { b.hidden = true; });
  });
})();
