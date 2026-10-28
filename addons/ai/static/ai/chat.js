// Chat dell'assistente: apertura dei pannelli laterali dalle icone, invio con Invio, scorrimento in fondo.
(function () {
  const chat = document.querySelector('[data-ai-chat]');
  if (!chat) return;
  const messaggi = chat.querySelector('#ai-messaggi');
  const input = chat.querySelector('.ai-input');
  const form = chat.querySelector('.ai-composer');

  const inFondo = () => { messaggi.scrollTop = messaggi.scrollHeight; };

  // Pannelli: un'icona apre il suo contenuto; cliccata di nuovo (o con Esc / la X) richiude il pannello.
  const chiudi = (lato) => {
    const pannello = chat.querySelector(`#ai-pannello-${lato}`);
    pannello.hidden = true;
    pannello.querySelectorAll('section').forEach((s) => { s.hidden = true; });
    chat.querySelectorAll(`[data-lato="${lato}"]`).forEach((b) => b.setAttribute('aria-expanded', 'false'));
  };
  chat.querySelectorAll('[data-pannello]').forEach((bottone) => {
    bottone.addEventListener('click', () => {
      const lato = bottone.dataset.lato;
      const giaAperto = bottone.getAttribute('aria-expanded') === 'true';
      chiudi(lato);
      if (giaAperto) return;
      const pannello = chat.querySelector(`#ai-pannello-${lato}`);
      pannello.hidden = false;
      pannello.querySelector(`[data-contenuto="${bottone.dataset.pannello}"]`).hidden = false;
      bottone.setAttribute('aria-expanded', 'true');
    });
  });
  chat.querySelectorAll('[data-chiudi]').forEach((x) => x.addEventListener('click', () => {
    chiudi(x.closest('.ai-pannello').id.replace('ai-pannello-', ''));
  }));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { chiudi('sinistra'); chiudi('destra'); }
  });

  // Composer: Invio invia, Maiusc+Invio va a capo; l'area cresce con il testo.
  const adatta = () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 200)}px`; };
  input.addEventListener('input', adatta);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (input.value.trim()) form.requestSubmit();
    }
  });
  // Dopo la risposta (HTMX): via il benvenuto, campo vuoto, in fondo alla conversazione.
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (e.detail.target !== messaggi) return;
    const benvenuto = messaggi.querySelector('.ai-benvenuto');
    if (benvenuto) benvenuto.remove();
    input.value = '';
    adatta();
    inFondo();
  });
  document.body.addEventListener('htmx:beforeRequest', (e) => {
    if (e.detail.elt === form) form.querySelector('.ai-invia').disabled = true;
  });
  document.body.addEventListener('htmx:afterRequest', (e) => {
    if (e.detail.elt === form) { form.querySelector('.ai-invia').disabled = false; input.focus(); }
  });
  inFondo();
  input.focus();
})();
