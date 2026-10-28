// Chat dell'assistente: pannelli laterali dalle icone, composer (Invio invia), suggerimenti,
// scelta dell'app a cui limitare la chat, scorrimento in fondo dopo ogni risposta.
(function () {
  const chat = document.querySelector('[data-ai-chat]');
  if (!chat) return;
  const scorri = chat.querySelector('#ai-scorri');
  const messaggi = chat.querySelector('#ai-messaggi');
  const form = chat.querySelector('.ai-composer');
  const input = form.querySelector('.ai-input');
  const invia = form.querySelector('.ai-invia');

  const inFondo = () => { scorri.scrollTop = scorri.scrollHeight; };

  // --- pannelli: un'icona apre il suo contenuto; di nuovo (o Esc, o la X) lo richiude ---
  const chiudi = (lato) => {
    const pannello = chat.querySelector(`#ai-pannello-${lato}`);
    pannello.hidden = true;
    pannello.querySelectorAll('section').forEach((s) => { s.hidden = true; });
    chat.querySelectorAll(`[data-lato="${lato}"]`).forEach((b) => b.setAttribute('aria-expanded', 'false'));
  };
  chat.querySelectorAll('[data-pannello]').forEach((bottone) => {
    bottone.addEventListener('click', () => {
      const lato = bottone.dataset.lato;
      const aperto = bottone.getAttribute('aria-expanded') === 'true';
      chiudi(lato);
      if (aperto) return;
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

  // --- composer: cresce con il testo; Invio invia, Maiusc+Invio va a capo ---
  const aggiorna = () => {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 260)}px`;
    invia.disabled = !input.value.trim();
  };
  input.addEventListener('input', aggiorna);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (input.value.trim()) form.requestSubmit();
    }
  });

  // --- suggerimenti: un clic li mette nel composer ---
  const lista = chat.querySelector('[data-suggerimenti]');
  const collegaSuggerimenti = () => {
    if (!lista) return;
    lista.querySelectorAll('[data-sugg]').forEach((b) => b.addEventListener('click', () => {
      input.value = b.textContent.trim();
      aggiorna();
      input.focus();
    }));
  };
  collegaSuggerimenti();

  // --- app a cui limitare la chat: una sola alla volta, con il chip nel composer ---
  const datiApp = document.getElementById('ai-suggerimenti-app');
  const suggerimentiApp = datiApp ? JSON.parse(datiApp.textContent) : {};
  const campoAmbito = form.querySelector('[data-ambito]');
  const chip = form.querySelector('[data-chip-ambito]');
  const mostraSuggerimenti = (slug) => {
    if (!lista) return;
    const voci = suggerimentiApp[slug] || suggerimentiApp[''] || [];
    lista.replaceChildren(...voci.map((testo) => {
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'ai-sugg'; b.dataset.sugg = ''; b.textContent = testo;
      li.appendChild(b);
      return li;
    }));
    collegaSuggerimenti();
  };
  const scegli = (bottone) => {
    const giaScelto = bottone && bottone.getAttribute('aria-pressed') === 'true';
    chat.querySelectorAll('[data-ambito-app]').forEach((b) => b.setAttribute('aria-pressed', 'false'));
    if (!bottone || giaScelto) {
      campoAmbito.value = '';
      if (chip) chip.hidden = true;
      mostraSuggerimenti('');
      return;
    }
    bottone.setAttribute('aria-pressed', 'true');
    campoAmbito.value = bottone.dataset.ambitoApp;
    if (chip) {
      chip.querySelector('[data-chip-nome]').textContent = bottone.dataset.nome;
      const img = chip.querySelector('img');
      img.hidden = !bottone.dataset.icona;
      if (bottone.dataset.icona) img.src = bottone.dataset.icona;
      chip.hidden = false;
    }
    mostraSuggerimenti(bottone.dataset.ambitoApp);
    input.focus();
  };
  chat.querySelectorAll('[data-ambito-app]').forEach((b) => b.addEventListener('click', () => scegli(b)));
  const togli = form.querySelector('[data-togli-ambito]');
  if (togli) togli.addEventListener('click', () => scegli(null));

  // --- dopo la risposta (HTMX): campo vuoto e conversazione in fondo ---
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (e.detail.target !== messaggi) return;
    input.value = '';
    aggiorna();
    inFondo();
  });
  document.body.addEventListener('htmx:beforeRequest', (e) => {
    if (e.detail.elt === form) invia.disabled = true;
  });
  document.body.addEventListener('htmx:afterRequest', (e) => {
    if (e.detail.elt === form) { aggiorna(); input.focus(); }
  });

  aggiorna();
  inFondo();
  input.focus();
})();
