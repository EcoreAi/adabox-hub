// Discuss: scorrimento in fondo, Invio per mandare, pulizia del modulo dopo l'invio.
(function () {
  const lista = document.getElementById('ds-messaggi');
  const inFondo = () => !lista || lista.scrollHeight - lista.scrollTop - lista.clientHeight < 120;
  const vaiInFondo = () => { if (lista) lista.scrollTop = lista.scrollHeight; };
  vaiInFondo();
  let eraInFondo = true;
  document.body.addEventListener('htmx:beforeSwap', (ev) => { if (ev.detail.target && ev.detail.target.id === 'ds-poller') eraInFondo = inFondo(); });
  document.body.addEventListener('htmx:afterSwap', (ev) => {
    if (!lista || !ev.detail.target) return;
    if (ev.detail.target.id === 'ds-poller' || ev.detail.elt?.id === 'ds-poller') {
      const vuoto = lista.querySelector('[data-vuoto]');
      if (vuoto && lista.querySelector('.ds-messaggio')) vuoto.remove();
      if (eraInFondo) vaiInFondo();
    }
  });

  const modulo = document.querySelector('[data-scrivi]');
  if (!modulo) return;
  const area = modulo.querySelector('textarea');
  const file = modulo.querySelector('[data-file]');
  const scelti = modulo.querySelector('[data-scelti]');
  area.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      if (area.value.trim() || (file && file.files.length)) modulo.requestSubmit();
    }
  });
  if (file) file.addEventListener('change', () => { scelti.textContent = Array.from(file.files).map((f) => f.name).join(', '); });
  modulo.addEventListener('htmx:afterRequest', (ev) => {
    if (ev.detail.successful) {
      modulo.reset();
      scelti.textContent = '';
      eraInFondo = true;
      area.focus();
    } else if (ev.detail.xhr && ev.detail.xhr.status === 422) {
      alert(ev.detail.xhr.responseText);
    }
  });
  area.focus();
})();
