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

  const campoFile = form.querySelector('[data-file]');
  const inFondo = () => { scorri.scrollTop = scorri.scrollHeight; };

  // --- pannelli: un'icona apre il suo contenuto; di nuovo (o Esc, o la X) lo richiude. Il pannello aperto di
  //     ogni lato si ricorda; la prima volta, su schermi larghi, la cronologia è aperta ---
  const LARGO = window.matchMedia('(min-width: 1200px)');
  const ricorda = (lato, chiave) => {
    try { localStorage.setItem(`ai-pannello-${lato}`, chiave); } catch (e) { /* archivio non disponibile */ }
  };
  const ricordato = (lato) => {
    try { return localStorage.getItem(`ai-pannello-${lato}`); } catch (e) { return null; }
  };
  const chiudi = (lato, salva = true) => {
    const pannello = chat.querySelector(`#ai-pannello-${lato}`);
    pannello.hidden = true;
    pannello.querySelectorAll('section').forEach((s) => { s.hidden = true; });
    chat.querySelectorAll(`[data-lato="${lato}"]`).forEach((b) => b.setAttribute('aria-expanded', 'false'));
    if (salva) ricorda(lato, '');
  };
  const apri = (lato, chiave) => {
    const bottone = chat.querySelector(`[data-lato="${lato}"][data-pannello="${chiave}"]`);
    const sezione = chat.querySelector(`#ai-pannello-${lato} [data-contenuto="${chiave}"]`);
    if (!bottone || !sezione) return;
    chiudi(lato, false);
    chat.querySelector(`#ai-pannello-${lato}`).hidden = false;
    sezione.hidden = false;
    bottone.setAttribute('aria-expanded', 'true');
    ricorda(lato, chiave);
  };
  chat.querySelectorAll('[data-pannello]').forEach((bottone) => {
    bottone.addEventListener('click', () => {
      const lato = bottone.dataset.lato;
      if (bottone.getAttribute('aria-expanded') === 'true') chiudi(lato); else apri(lato, bottone.dataset.pannello);
    });
  });
  chat.querySelectorAll('[data-chiudi]').forEach((x) => x.addEventListener('click', () => {
    chiudi(x.closest('.ai-pannello').id.replace('ai-pannello-', ''));
  }));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { chiudi('sinistra'); chiudi('destra'); }
  });
  if (LARGO.matches) {                            // su schermi stretti i pannelli coprono la chat: chiusi
    const sinistra = ricordato('sinistra');
    if (sinistra === null) apri('sinistra', 'storico'); else if (sinistra) apri('sinistra', sinistra);
    const destra = ricordato('destra');
    if (destra) apri('destra', destra);
  }

  // --- composer: cresce con il testo; Invio invia, Maiusc+Invio va a capo ---
  const aggiorna = () => {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 260)}px`;
    invia.disabled = (!input.value.trim() && !(campoFile && campoFile.files.length)) || !!messaggi.querySelector('[data-flusso]');
  };
  input.addEventListener('input', aggiorna);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (input.value.trim() || (campoFile && campoFile.files.length)) form.requestSubmit();
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

  // --- app a cui limitare la chat: dalle icone sotto il campo (chat nuova) o dal bottone «App» nel campo (sempre).
  //     Una sola alla volta, mostrata dal chip; in una chat già avviata vale dal messaggio successivo ---
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
  const scegli = (slug, focus = true) => {
    campoAmbito.value = slug;
    chat.querySelectorAll('[data-ambito-app]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.ambitoApp === slug)));
    const fonte = slug && chat.querySelector(`[data-ambito-app="${slug}"][data-nome]`);
    if (chip) {
      chip.hidden = !fonte;
      if (fonte) {
        chip.querySelector('[data-chip-nome]').textContent = fonte.dataset.nome;
        const img = chip.querySelector('img');
        img.hidden = !fonte.dataset.icona;
        if (fonte.dataset.icona) img.src = fonte.dataset.icona;
      }
    }
    mostraSuggerimenti(slug);
    if (focus) input.focus();
  };
  // icone sotto il campo: un clic sceglie, un altro clic sulla stessa toglie la scelta
  chat.querySelectorAll('.ai-ambito[data-ambito-app]').forEach((b) => b.addEventListener('click', () => {
    scegli(b.getAttribute('aria-pressed') === 'true' ? '' : b.dataset.ambitoApp);
  }));
  const togli = form.querySelector('[data-togli-ambito]');
  if (togli) togli.addEventListener('click', () => scegli(''));

  // bottone «App» nel campo: apre la scheda con le app; si chiude scegliendo, con Esc o cliccando fuori
  const apriApp = form.querySelector('[data-apri-app]');
  const scheda = form.querySelector('#ai-scheda-app');
  const chiudiScheda = () => {
    if (!scheda || scheda.hidden) return;
    scheda.hidden = true;
    apriApp.setAttribute('aria-expanded', 'false');
  };
  if (apriApp && scheda) {
    apriApp.addEventListener('click', (e) => {
      e.stopPropagation();
      const aperta = !scheda.hidden;
      scheda.hidden = aperta;
      apriApp.setAttribute('aria-expanded', String(!aperta));
      if (!aperta) (scheda.querySelector('[aria-pressed="true"]') || scheda.querySelector('button')).focus();
    });
    scheda.querySelectorAll('[data-ambito-app]').forEach((b) => b.addEventListener('click', () => {
      scegli(b.dataset.ambitoApp);
      chiudiScheda();
    }));
    document.addEventListener('click', (e) => { if (!scheda.contains(e.target)) chiudiScheda(); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !scheda.hidden) { chiudiScheda(); apriApp.focus(); }
    });
  }

  // le icone sotto il campo si nascondono con un clic sul titolo (scelta ricordata)
  const interruttore = chat.querySelector('[data-interruttore-ambiti]');
  if (interruttore) {
    const griglia = chat.querySelector('#ai-ambiti-griglia');
    const imposta = (visibili) => {
      griglia.hidden = !visibili;
      interruttore.setAttribute('aria-expanded', String(visibili));
    };
    let nascoste = false;
    try { nascoste = localStorage.getItem('ai-ambiti-nascosti') === '1'; } catch (e) { /* archivio non disponibile */ }
    imposta(!nascoste);
    interruttore.addEventListener('click', () => {
      const visibili = griglia.hidden;
      imposta(visibili);
      try { localStorage.setItem('ai-ambiti-nascosti', visibili ? '0' : '1'); } catch (e) { /* idem */ }
    });
  }
  if (campoAmbito.value) scegli(campoAmbito.value, false);

  // --- allegati: il «+» apre la scelta, i nomi restano nel campo finché non si invia ---
  const listaFile = form.querySelector('[data-allegati]');
  const avviso = chat.querySelector('[data-errore]');
  const mostraErrore = (testo) => { avviso.textContent = testo; avviso.hidden = !testo; };
  function mostraFile() {
    listaFile.replaceChildren(...[...campoFile.files].map((f, i) => {
      const li = document.createElement('li');
      const chipFile = document.createElement('span');
      chipFile.className = 'ai-chip';
      chipFile.textContent = f.name;
      const x = document.createElement('button');
      x.type = 'button'; x.className = 'ai-chip-x'; x.textContent = '×'; x.setAttribute('aria-label', `Togli ${f.name}`);
      x.addEventListener('click', () => {
        const dt = new DataTransfer();
        [...campoFile.files].forEach((g, j) => { if (j !== i) dt.items.add(g); });
        campoFile.files = dt.files;
        mostraFile();
        aggiorna();
      });
      chipFile.appendChild(x);
      li.appendChild(chipFile);
      return li;
    }));
    listaFile.hidden = !campoFile.files.length;
  }
  form.querySelector('[data-allega]').addEventListener('click', () => campoFile.click());
  campoFile.addEventListener('change', () => { mostraErrore(''); mostraFile(); aggiorna(); });
  document.body.addEventListener('ai-errore', (e) => { mostraErrore(e.detail.value); aggiorna(); });

  // --- azioni sui messaggi: copia (anche senza HTTPS, dove il browser non dà gli appunti), modifica, rigenera ---
  const copia = (testo, bottone) => {
    const originale = bottone.dataset.etichetta || bottone.textContent;
    bottone.dataset.etichetta = originale;
    const avvisa = (scritta) => { bottone.textContent = scritta; setTimeout(() => { bottone.textContent = originale; }, 1200); };
    const ripiego = () => {                       // senza HTTPS, o se il browser nega gli appunti
      const area = document.createElement('textarea');
      area.value = testo; area.style.position = 'fixed'; area.style.opacity = '0';
      document.body.appendChild(area); area.select();
      let riuscito = false;
      try { riuscito = document.execCommand('copy'); } catch (err) { /* non permesso */ }
      area.remove();
      avvisa(riuscito ? 'Copiato' : 'Non copiato');
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(testo).then(() => avvisa('Copiato'), ripiego);
    else ripiego();
  };
  function decoraCodice(radice) {
    radice.querySelectorAll('pre').forEach((pre) => {
      if (pre.querySelector('[data-copia-codice]')) return;
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'ai-copia-codice'; b.dataset.copiaCodice = ''; b.textContent = 'Copia';
      b.addEventListener('click', () => copia(pre.querySelector('code').innerText, b));
      pre.appendChild(b);
    });
  }
  function decora() {
    decoraCodice(messaggi);
    const risposte = messaggi.querySelectorAll('.ai-msg-assistente:not(.is-in-corso)');
    messaggi.querySelectorAll('[data-solo-ultima]').forEach((f) => { f.hidden = true; });
    const ultima = risposte[risposte.length - 1];
    const dopo = ultima && !messaggi.querySelector('[data-flusso]') && ultima.querySelector('[data-solo-ultima]');
    if (dopo) dopo.hidden = false;
  }
  messaggi.addEventListener('click', (e) => {
    const articolo = e.target.closest('[data-messaggio]');
    if (!articolo) return;
    const bottone = e.target.closest('[data-copia]');
    if (bottone) copia(articolo.querySelector('.ai-msg-testo').innerText, bottone);
    const moduloModifica = articolo.querySelector('[data-modifica]');
    if (e.target.closest('[data-apri-modifica]')) { moduloModifica.hidden = false; moduloModifica.querySelector('textarea').focus(); }
    if (e.target.closest('[data-annulla-modifica]')) moduloModifica.hidden = true;
  });
  const apriRinomina = chat.querySelector('[data-apri-rinomina]');
  if (apriRinomina) apriRinomina.addEventListener('click', () => {
    const modulo = chat.querySelector('[data-rinomina]');
    modulo.hidden = false;
    chat.querySelector('[data-titolo]').hidden = true;
    modulo.querySelector('input[name="titolo"]').select();
  });

  // --- risposta in diretta: la bolla "in corso" segue il turno con Server-Sent Events ---
  const csrf = form.querySelector('input[name="csrfmiddlewaretoken"]').value;
  const NOMI = {
    data_e_ora: 'controllo data e ora', app_disponibili: 'guardo le app disponibili',
    elenco_viste: 'guardo dove sono i dati', descrivi_vista: 'leggo la struttura dei dati',
    cerca_record: 'cerco i record', leggi_record: 'leggo il record', aggrega_record: 'calcolo i totali',
    crea_record: 'preparo il nuovo record', modifica_record: 'preparo la modifica',
    elimina_record: "preparo l'eliminazione", esegui_bottone: "preparo l'operazione",
    esegui_azione: "preparo l'operazione", pianifica_attivita: "preparo l'attività",
    grafico: 'disegno il grafico', tabella: 'preparo la tabella',
    crea_pianificata: "preparo l'attività pianificata", elenco_pianificate: 'guardo le attività pianificate',
    cerca_conoscenza: 'cerco nei documenti e nelle note', leggi_documento: 'leggo il documento',
    leggi_foglio: 'leggo il foglio', leggi_allegato: "leggo l'allegato", previsione: 'calcolo la previsione', classifica: 'valuto il testo',
    elenco_esperti: 'guardo quali esperti ci sono', chiedi_esperto: "chiedo all'esperto", riassunto: 'riassumo la conversazione',
  };
  const segui = (bolla) => {
    if (!bolla || bolla.dataset.seguita) return;
    bolla.dataset.seguita = '1';
    invia.disabled = true;
    const coda = bolla.querySelector('[data-coda]');
    const reso = bolla.querySelector('[data-reso]');
    const avanzamento = bolla.querySelector('[data-avanzamento]');
    const sorgente = new EventSource(bolla.dataset.flusso);
    // flusso caduto per sempre (es. 502 dal proxy): la risposta è comunque nel database, si ricarica la pagina
    sorgente.addEventListener('error', () => {
      if (sorgente.readyState === EventSource.CLOSED) setTimeout(() => window.location.reload(), 3000);
    });
    sorgente.addEventListener('testo', (e) => {
      const vicinoAlFondo = scorri.scrollHeight - scorri.scrollTop - scorri.clientHeight < 120;
      coda.textContent += JSON.parse(e.data).delta;
      if (vicinoAlFondo) inFondo();
    });
    // il testo formattato arriva già pronto e sicuro dal server: nel browser non si interpreta Markdown
    sorgente.addEventListener('html', (e) => {
      const vicinoAlFondo = scorri.scrollHeight - scorri.scrollTop - scorri.clientHeight < 120;
      reso.innerHTML = JSON.parse(e.data).html;
      coda.textContent = '';
      decoraCodice(reso);
      if (vicinoAlFondo) inFondo();
    });
    sorgente.addEventListener('avanzamento', (e) => {
      const voci = JSON.parse(e.data);
      const ultima = voci[voci.length - 1];
      if (!ultima) return;
      const nomi = ultima.strumento ? [ultima.strumento] : (ultima.fatti || []).map((f) => f.strumento);
      avanzamento.textContent = ultima.strumento
        ? `${NOMI[ultima.strumento] || `uso «${ultima.strumento}»`}…`
        : `fatto: ${nomi.map((n) => NOMI[n] || n).join(', ')}`;
    });
    sorgente.addEventListener('fine', (e) => {
      sorgente.close();
      const dati = JSON.parse(e.data);
      if (dati.html) bolla.outerHTML = dati.html; else bolla.remove();
      if (window.htmx) window.htmx.process(messaggi);
      decora();
      aggiorna();
      inFondo();
      input.focus();
    });
    const ferma = bolla.querySelector('[data-ferma]');
    if (ferma) ferma.addEventListener('click', () => {
      ferma.disabled = true;
      fetch(bolla.dataset.stop, { method: 'POST', headers: { 'X-CSRFToken': csrf } });
    });
  };
  const seguiInCorso = () => messaggi.querySelectorAll('[data-flusso]').forEach(segui);

  // --- dopo l'invio (HTMX): campo vuoto, conversazione in fondo, risposta in diretta ---
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (e.detail.target !== messaggi) return;
    input.value = '';
    if (campoFile) { campoFile.value = ''; mostraFile(); }
    decora();
    aggiorna();
    inFondo();
    seguiInCorso();
  });
  document.body.addEventListener('htmx:beforeRequest', (e) => {
    if (e.detail.elt === form) invia.disabled = true;
  });
  document.body.addEventListener('htmx:afterRequest', (e) => {
    if (e.detail.elt === form && !messaggi.querySelector('[data-flusso]')) { aggiorna(); input.focus(); }
  });

  decora();
  aggiorna();
  inFondo();
  seguiInCorso();
  input.focus();
})();
