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
  const apri = (lato, chiave, salva = true) => {
    const bottone = chat.querySelector(`[data-lato="${lato}"][data-pannello="${chiave}"]`);
    const sezione = chat.querySelector(`#ai-pannello-${lato} [data-contenuto="${chiave}"]`);
    if (!bottone || !sezione) return;
    chiudi(lato, false);
    chat.querySelector(`#ai-pannello-${lato}`).hidden = false;
    sezione.hidden = false;
    bottone.setAttribute('aria-expanded', 'true');
    if (salva) ricorda(lato, chiave);
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
    // dentro un progetto (sua pagina o sua chat) si vede la sua cartella, se il pannello di sinistra è aperto
    if (chat.hasAttribute('data-in-progetto') && sinistra !== '') apri('sinistra', 'progetti', false);
    else if (sinistra === null) apri('sinistra', 'storico'); else if (sinistra) apri('sinistra', sinistra);
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
    chat.classList.remove('con-scheda');
  };
  // larga come il menu della testata: si apre sotto il campo (chat nuova) o sopra (conversazione), dentro lo schermo
  const posiziona = () => {
    const campo = form.getBoundingClientRect();
    const larghezza = Math.min(1040, window.innerWidth - 32);
    const sinistra = Math.max(16, Math.min(campo.left + campo.width / 2 - larghezza / 2, window.innerWidth - larghezza - 16));
    Object.assign(scheda.style, { width: `${larghezza}px`, left: `${sinistra}px` });
    const testata = document.querySelector('.ui-header');
    const cima = testata ? testata.getBoundingClientRect().bottom : 0;      // mai sotto la testata della pagina
    const sotto = window.innerHeight - campo.bottom > campo.top - cima;
    scheda.style.top = sotto ? `${campo.bottom + 10}px` : 'auto';
    scheda.style.bottom = sotto ? 'auto' : `${window.innerHeight - campo.top + 10}px`;
    scheda.style.maxHeight = `${(sotto ? window.innerHeight - campo.bottom : campo.top - cima) - 26}px`;
  };
  if (apriApp && scheda) {
    apriApp.addEventListener('click', (e) => {
      e.stopPropagation();
      const aperta = !scheda.hidden;
      if (aperta) { chiudiScheda(); return; }
      posiziona();
      scheda.hidden = false;
      chat.classList.add('con-scheda');
      apriApp.setAttribute('aria-expanded', 'true');
      (scheda.querySelector('[aria-pressed="true"]') || scheda.querySelector('button')).focus();
    });
    window.addEventListener('resize', () => { if (!scheda.hidden) posiziona(); });
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
    aggiornaConferma();
  }
  // immagini verso un modello cloud: l'azienda lascia decidere all'utente, immagine per immagine
  const boxConferma = form.querySelector('[data-conferma-box]');
  const campoConferma = form.querySelector('[data-conferma-campo]');
  const conImmagini = () => [...campoFile.files].some((f) => f.type.startsWith('image/'));
  const daConfermare = () => Boolean(boxConferma) && conImmagini() && campoConferma.value !== '1';
  function aggiornaConferma() {
    if (!boxConferma) return;
    if (!conImmagini()) campoConferma.value = '';
    const fatta = campoConferma.value === '1';
    boxConferma.hidden = !conImmagini();
    boxConferma.classList.toggle('is-confermata', fatta);
    boxConferma.querySelector('[data-conferma-domanda]').hidden = fatta;
    boxConferma.querySelector('[data-conferma-fatta]').hidden = !fatta;
    boxConferma.querySelector('[data-conferma-bottoni]').hidden = fatta;
  }
  if (boxConferma) {
    boxConferma.querySelector('[data-conferma-si]').addEventListener('click', () => { campoConferma.value = '1'; aggiornaConferma(); input.focus(); });
    boxConferma.querySelector('[data-conferma-togli]').addEventListener('click', () => {
      const dt = new DataTransfer();
      [...campoFile.files].forEach((f) => { if (!f.type.startsWith('image/')) dt.items.add(f); });
      campoFile.files = dt.files;
      mostraFile();
      aggiorna();
      input.focus();
    });
    // senza conferma non si invia: si mostra di nuovo il riquadro
    const ferma = (e) => {
      if (!daConfermare()) return;
      e.preventDefault();
      boxConferma.classList.remove('is-richiamo'); void boxConferma.offsetWidth; boxConferma.classList.add('is-richiamo');
      boxConferma.querySelector('[data-conferma-si]').focus();
    };
    form.addEventListener('submit', ferma, true);
    document.body.addEventListener('htmx:beforeRequest', (e) => { if (e.detail.elt === form) ferma(e); });
  }
  form.querySelector('[data-allega]').addEventListener('click', () => campoFile.click());
  // file scelti di nuovo: la conferma delle immagini vale per quelle viste, si chiede ancora
  campoFile.addEventListener('change', () => { mostraErrore(''); if (campoConferma) campoConferma.value = ''; mostraFile(); aggiorna(); });
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
    leggi_immagine: "leggo l'immagine sul server", scrivi_documento: 'scrivo il documento', leggi_documento_chat: 'leggo il documento', modifica_documento: 'modifico il documento',
    data_e_ora: 'controllo data e ora', app_disponibili: 'guardo le app disponibili',
    elenco_viste: 'guardo dove sono i dati', descrivi_vista: 'leggo la struttura dei dati',
    cerca_record: 'cerco i record', leggi_record: 'leggo il record', aggrega_record: 'calcolo i totali',
    crea_record: 'preparo il nuovo record', modifica_record: 'preparo la modifica',
    elimina_record: "preparo l'eliminazione", esegui_bottone: "preparo l'operazione",
    esegui_azione: "preparo l'operazione", pianifica_attivita: "preparo l'attività",
    grafico: 'disegno il grafico', tabella: 'preparo la tabella',
    crea_pianificata: "preparo l'attività pianificata", elenco_pianificate: 'guardo le attività pianificate',
    cerca_conoscenza: 'cerco nei documenti e nelle note', leggi_documento: 'leggo il documento',
    leggi_foglio: 'leggo il foglio', leggi_allegato: "leggo l'allegato", cerca_web: 'cerco sul web', leggi_pagina: 'leggo la pagina', ricorda: 'preparo il ricordo', previsione: 'calcolo la previsione', classifica: 'valuto il testo',
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
      document.dispatchEvent(new CustomEvent('ai:risposta-finita'));
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
    if (campoConferma) campoConferma.value = '';
    if (campoFile) { campoFile.value = ''; mostraFile(); }
    form.querySelectorAll('[data-menu-icona][data-reimposta]').forEach((m) => m.scegli && m.scegli(''));
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

  // --- menu a icona (ricerca sul web, modello): l'icona mostra la scelta, il menu le opzioni ---
  document.querySelectorAll('[data-menu-icona]').forEach((menu) => {
    const bottone = menu.querySelector('[data-apri-menu]');
    const tendina = menu.querySelector('[role=menu]');
    const valore = menu.querySelector('[data-valore]');
    const opzioni = [...tendina.querySelectorAll('[data-opzione]')];
    const chiudi = () => { tendina.hidden = true; bottone.setAttribute('aria-expanded', 'false'); };
    menu.scegli = (v) => {
      const scelta = opzioni.find((o) => o.dataset.opzione === v) || opzioni[0];
      valore.value = scelta.dataset.opzione;
      opzioni.forEach((o) => o.setAttribute('aria-checked', String(o === scelta)));
      bottone.querySelector('use').setAttribute('href', `#${scelta.dataset.icona}`);
      bottone.dataset.tip = scelta.dataset.etichetta;
      bottone.setAttribute('aria-label', scelta.dataset.etichetta);
      bottone.classList.toggle('is-attivo', scelta.dataset.opzione !== '');
    };
    menu.scegli(valore.value);
    bottone.addEventListener('click', (e) => {
      e.stopPropagation();
      const aperta = !tendina.hidden;
      document.querySelectorAll('[data-menu-icona] [role=menu]').forEach((t) => { t.hidden = true; });
      if (aperta) { chiudi(); return; }
      tendina.hidden = false;
      bottone.setAttribute('aria-expanded', 'true');
      (opzioni.find((o) => o.getAttribute('aria-checked') === 'true') || opzioni[0]).focus();
    });
    opzioni.forEach((o) => o.addEventListener('click', () => { menu.scegli(o.dataset.opzione); chiudi(); bottone.focus(); }));
    tendina.addEventListener('keydown', (e) => {
      const i = opzioni.indexOf(document.activeElement);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        opzioni[(i + (e.key === 'ArrowDown' ? 1 : opzioni.length - 1)) % opzioni.length].focus();
      }
    });
    document.addEventListener('click', (e) => { if (!menu.contains(e.target)) chiudi(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !tendina.hidden) { chiudi(); bottone.focus(); } });
  });

  // --- colonna di sinistra: le sottocartelle di un progetto si caricano quando lo si apre ---
  const caricaAlbero = (dettagli) => {
    const contenitore = dettagli.querySelector('[data-albero-contenuto]');
    if (!contenitore || contenitore.dataset.caricato || !window.htmx) return;
    contenitore.dataset.caricato = '1';
    window.htmx.ajax('GET', dettagli.dataset.albero, { target: contenitore, swap: 'innerHTML' });
  };
  document.querySelectorAll('details[data-albero]').forEach((dettagli) => {
    dettagli.addEventListener('toggle', () => { if (dettagli.open) caricaAlbero(dettagli); });
    if (dettagli.open) caricaAlbero(dettagli);
  });
  // dopo una risposta (chat nuova, documento, grafico) l'albero aperto si aggiorna
  document.addEventListener('ai:risposta-finita', () => setTimeout(() => {
    document.querySelectorAll('details[data-albero][open] [data-albero-contenuto]').forEach((c) => {
      delete c.dataset.caricato; caricaAlbero(c.closest('details'));
    });
  }, 400));

  // --- «Salva nei Documenti»: documenti scritti con Ada, grafici e tabelle nell'archivio, nella cartella scelta ---
  const salvaDoc = document.getElementById('ai-salva-doc');
  const mostraSalva = () => {
    if (salvaDoc) document.querySelectorAll('[data-salva-documenti][hidden]').forEach((b) => { b.hidden = false; });
  };
  if (salvaDoc) {
    const esito = salvaDoc.querySelector('[data-salva-esito]');
    const conferma = salvaDoc.querySelector('[data-salva-conferma]');
    document.addEventListener('click', (e) => {
      const b = e.target.closest('[data-salva-documenti]');
      if (!b) return;
      salvaDoc.dataset.url = b.dataset.salvaDocumenti;
      salvaDoc.querySelector('[data-salva-cosa]').textContent = `Salva ${b.dataset.cosa}.`;
      esito.hidden = true; esito.replaceChildren(); conferma.hidden = false; conferma.disabled = false;
      salvaDoc.querySelector('[data-salva-chiudi]').textContent = 'Annulla';
      salvaDoc.showModal();
    });
    conferma.addEventListener('click', async () => {
      conferma.disabled = true;
      const dati = new FormData();
      dati.append('cartella', salvaDoc.querySelector('[data-salva-cartella]').value);
      try {
        const r = await fetch(salvaDoc.dataset.url, { method: 'POST', body: dati, headers: { 'X-CSRFToken': csrf } });
        const j = await r.json();
        if (!r.ok) throw new Error(j.errore || 'Salvataggio non riuscito.');
        const link = document.createElement('a');
        link.href = j.url; link.className = 'ui-link'; link.textContent = 'Apri nei Documenti';
        esito.replaceChildren(document.createTextNode(`${j.messaggio} `), link);
        conferma.hidden = true;
        salvaDoc.querySelector('[data-salva-chiudi]').textContent = 'Chiudi';
      } catch (err) {
        esito.textContent = err.message; conferma.disabled = false;
      }
      esito.hidden = false;
    });
  }
  document.body.addEventListener('htmx:afterSettle', mostraSalva);
  document.addEventListener('ai:risposta-finita', () => setTimeout(mostraSalva, 80));
  mostraSalva();

  // --- pagina del progetto: file o una cartella intera dal PC nella cartella dei Documenti ---
  const caricaArchivio = document.querySelector('[data-carica-archivio]');
  if (caricaArchivio) {
    const stato = caricaArchivio.querySelector('[data-carica-stato]');
    caricaArchivio.querySelectorAll('[data-scegli]').forEach((b) => b.addEventListener('click', () => {
      caricaArchivio.querySelector(b.dataset.scegli === 'cartella' ? '[data-carica-cartella]' : '[data-carica-file]').click();
    }));
    caricaArchivio.querySelectorAll('input[type=file]').forEach((campo) => campo.addEventListener('change', async () => {
      if (!campo.files.length) return;
      const dati = new FormData();
      dati.append('csrfmiddlewaretoken', csrf);
      [...campo.files].forEach((f) => { dati.append('file', f); dati.append('percorso', f.webkitRelativePath || ''); });
      stato.textContent = `Carico ${campo.files.length} file…`;
      caricaArchivio.querySelectorAll('button').forEach((b) => { b.disabled = true; });
      await fetch(caricaArchivio.action, { method: 'POST', body: dati });
      window.location.reload();
    }));
  }

  // --- documento accanto alla chat: leggi o modifica, niente modifiche perse ---
  const tela = () => document.querySelector('[data-tela]');
  let modificato = false;
  const modo = (quale) => {
    const t = tela();
    if (!t) return;
    t.querySelectorAll('[data-modo]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.modo === quale)));
    t.querySelector('[data-letto]').hidden = quale !== 'leggi';
    t.querySelector('[data-scrittura]').hidden = quale !== 'modifica';
    if (quale === 'modifica') t.querySelector('textarea[name=testo]').focus();
  };
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-tela] [data-modo]');
    if (b) modo(b.dataset.modo);
  });
  document.addEventListener('input', (e) => {
    if (e.target.closest('[data-tela] [data-scrittura]')) modificato = true;
  });
  document.body.addEventListener('htmx:afterSwap', (e) => {
    if (e.detail.target && e.detail.target.id === 'ai-tela') modificato = false;
  });
  document.body.addEventListener('htmx:afterSettle', (e) => {
    const t = tela();
    if (t && e.detail.target === t && t.querySelector('[role=alert]') && t.querySelector('.ai-tela-perso')) modo('modifica');
  });
  // dopo una risposta di Ada il documento si ricarica, se non ci sono modifiche da salvare
  document.addEventListener('ai:risposta-finita', () => {
    const t = tela();
    if (!t || !window.htmx) return;
    if (modificato) {
      if (!t.querySelector('[data-avviso-cambiato]')) {
        const p = document.createElement('p');
        p.className = 'ai-avviso'; p.dataset.avvisoCambiato = '';
        p.textContent = 'Ada potrebbe aver cambiato il documento: salvando le tue modifiche ti avviserò se c\'è un conflitto.';
        t.querySelector('.ai-tela-schede').before(p);
      }
      return;
    }
    window.htmx.ajax('GET', t.dataset.url, { target: '#ai-tela', swap: 'outerHTML' });
  });
  window.addEventListener('beforeunload', (e) => { if (modificato) { e.preventDefault(); e.returnValue = ''; } });

  // --- voce: dettatura (Whisper sul server) e lettura delle risposte ---
  const statoVoce = document.querySelector('[data-voce-stato]');
  const dici = (testo) => { if (!statoVoce) return; statoVoce.textContent = testo || ''; statoVoce.hidden = !testo; };
  const microfono = document.querySelector('[data-microfono]');
  if (microfono) {
    let registratore = null; let pezzi = []; let timer = null; let secondi = 0;
    const ferma = () => { if (registratore && registratore.state === 'recording') registratore.stop(); };
    microfono.addEventListener('click', async () => {
      if (registratore && registratore.state === 'recording') { ferma(); return; }
      if (!navigator.mediaDevices || !window.MediaRecorder) { dici('Il browser non permette di usare il microfono su questa pagina (serve https).'); return; }
      let flusso;
      try { flusso = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (err) { dici('Microfono non disponibile o non permesso.'); return; }
      pezzi = []; secondi = 0;
      registratore = new MediaRecorder(flusso);
      registratore.addEventListener('dataavailable', (e) => { if (e.data.size) pezzi.push(e.data); });
      registratore.addEventListener('stop', async () => {
        clearInterval(timer); flusso.getTracks().forEach((t) => t.stop());
        microfono.classList.remove('is-attivo'); microfono.setAttribute('aria-pressed', 'false');
        const audio = new Blob(pezzi, { type: registratore.mimeType || 'audio/webm' });
        if (!audio.size) { dici(''); return; }
        dici('Trascrivo…');
        const dati = new FormData();
        dati.append('audio', audio, 'voce.' + ((audio.type.split('/')[1] || 'webm').split(';')[0]));
        try {
          const r = await fetch(microfono.dataset.url, { method: 'POST', body: dati, headers: { 'X-CSRFToken': csrf } });
          const j = await r.json();
          if (!r.ok) throw new Error(j.errore || 'Trascrizione non riuscita.');
          input.value = (input.value ? input.value.replace(/\s*$/, ' ') : '') + j.testo;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.focus(); dici('');
        } catch (err) { dici(err.message); }
      });
      registratore.start();
      microfono.classList.add('is-attivo'); microfono.setAttribute('aria-pressed', 'true');
      dici('Ti ascolto… 0:00 · tocca di nuovo il microfono per finire');
      timer = setInterval(() => {
        secondi += 1;
        dici(`Ti ascolto… ${Math.floor(secondi / 60)}:${String(secondi % 60).padStart(2, '0')} · tocca di nuovo il microfono per finire`);
        if (secondi >= 120) ferma();
      }, 1000);
    });
  }

  let lettura = null;                                   // {bottone, audio, fermo}
  const fermaLettura = () => {
    if (!lettura) return;
    lettura.fermo = true; lettura.audio.pause();
    lettura.bottone.setAttribute('aria-pressed', 'false'); lettura.bottone.textContent = 'Ascolta';
    lettura = null;
  };
  const leggi = async (bottone) => {
    fermaLettura();
    const corrente = { bottone, audio: new Audio(), fermo: false };
    lettura = corrente;
    bottone.setAttribute('aria-pressed', 'true'); bottone.textContent = 'Ferma';
    try {
      const r = await fetch(bottone.dataset.ascolta);
      const j = await r.json();
      if (!r.ok) throw new Error(j.errore || 'Lettura non disponibile.');
      const indirizzo = (i) => bottone.dataset.audio.replace(/0\/$/, `${i}/`);
      for (let i = 0; i < j.parti && !corrente.fermo; i += 1) {
        if (i + 1 < j.parti) fetch(indirizzo(i + 1));       // il pezzo dopo si prepara mentre si ascolta questo
        corrente.audio.src = indirizzo(i);
        await new Promise((fatto, errore) => {
          corrente.audio.onended = fatto; corrente.audio.onerror = () => errore(new Error('Audio non disponibile.'));
          corrente.audio.onpause = () => { if (corrente.fermo) fatto(); };
          corrente.audio.play().catch(errore);
        });
      }
    } catch (err) { dici(err.message); }
    if (lettura === corrente) fermaLettura();
  };
  const mostraAscolta = () => {
    if (!chat || !chat.hasAttribute('data-lettura')) return;
    document.querySelectorAll('[data-ascolta][hidden]').forEach((b) => { b.hidden = false; });
  };
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-ascolta]');
    if (!b) return;
    if (lettura && lettura.bottone === b) fermaLettura(); else leggi(b);
  });
  const automatica = document.querySelector('[data-voce-automatica]');
  const attivaAutomatica = () => automatica && automatica.getAttribute('aria-pressed') === 'true';
  if (automatica) {
    const segna = (si) => {
      automatica.setAttribute('aria-pressed', String(si));
      automatica.classList.toggle('is-attivo', si);
      automatica.dataset.tip = si ? 'Risposta vocale accesa: leggo ogni nuova risposta' : 'Risposta vocale: leggi ad alta voce ogni nuova risposta';
    };
    segna(localStorage.getItem('ai-voce-automatica') === '1');
    automatica.addEventListener('click', () => {
      const si = !attivaAutomatica();
      segna(si);
      localStorage.setItem('ai-voce-automatica', si ? '1' : '0');
      if (!si) fermaLettura();
    });
  }
  document.addEventListener('ai:risposta-finita', () => setTimeout(() => {
    mostraAscolta();
    if (!attivaAutomatica()) return;
    const tutti = messaggi.querySelectorAll('.ai-msg-assistente [data-ascolta]');
    if (tutti.length) leggi(tutti[tutti.length - 1]);
  }, 60));
  document.body.addEventListener('htmx:afterSwap', mostraAscolta);
  mostraAscolta();

  decora();
  aggiorna();
  inFondo();
  seguiInCorso();
  input.focus();
})();
