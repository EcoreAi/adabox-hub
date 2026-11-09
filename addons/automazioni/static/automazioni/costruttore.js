// Costruttore delle regole: disegna Quando / Se / Allora dal catalogo; al salvataggio il server ricontrolla tutto.
(() => {
  const form = document.querySelector('[data-costruttore]');
  if (!form) return;
  const DATI = JSON.parse(document.getElementById('au-dati').textContent);
  const INIZIALE = JSON.parse(document.getElementById('au-iniziale').textContent);
  const q = (s) => form.querySelector(s);
  const evento = q('[data-c-evento]');
  const giorni = q('[data-c-giorni]');
  const listaCondizioni = q('[data-c-lista-condizioni]');
  const listaAzioni = q('[data-c-lista-azioni]');
  const OPERATORI = {
    numero: [['maggiore', 'è almeno'], ['minore', 'è al massimo'], ['uguale', 'è uguale a']],
    testo: [['contiene', 'contiene'], ['non_contiene', 'non contiene'], ['uguale', 'è uguale a']],
    sino: [['si', 'è vero'], ['no', 'non è vero']],
    scelta: [['uguale', 'è'], ['diverso', 'non è']],
  };

  const eventoDi = (codice) => DATI.gruppi.flatMap((g) => g.eventi).find((e) => e.codice === codice);
  const dominio = () => DATI.domini[eventoDi(evento.value)?.dominio];

  const crea = (tag, attr = {}, ...figli) => {
    const el = document.createElement(tag);
    Object.entries(attr).forEach(([k, v]) => { if (k === 'class') el.className = v; else el[k] = v; });
    el.append(...figli);
    return el;
  };
  const scelta = (opzioni, valore, nome) => {
    const s = crea('select', { class: 'ui-input', name: '' });
    s.dataset.campo = nome;
    opzioni.forEach(([v, t]) => s.append(crea('option', { value: v, textContent: t })));
    if (valore !== undefined && valore !== null && opzioni.some(([v]) => String(v) === String(valore))) s.value = valore;
    return s;
  };
  const casella = (valore, nome, segnaposto, tipo = 'text') => {
    const i = crea('input', { class: 'ui-input', type: tipo, value: valore ?? '', placeholder: segnaposto, name: '' });
    i.dataset.campo = nome;
    return i;
  };
  const togli = () => {
    const b = crea('button', { type: 'button', class: 'au-togli', title: 'Togli', textContent: '×' });
    b.addEventListener('click', () => { b.closest('[data-voce]').remove(); ridisegnaAiuti(); });
    return b;
  };
  const riga = (...figli) => { const r = crea('div', { class: 'au-riga' }, ...figli, togli()); r.dataset.voce = ''; return r; };

  // ---- condizioni
  const aggiungiCondizione = (c = {}) => {
    const d = dominio();
    if (!d || !d.condizioni.length) return;
    const campo = scelta(d.condizioni.map((x) => [x.nome, x.etichetta]), c.campo, 'campo');
    const posto = crea('span', { class: 'au-riga-valore' });
    const disegna = (op, valore) => {
      const voce = d.condizioni.find((x) => x.nome === campo.value);
      posto.replaceChildren(scelta(OPERATORI[voce.tipo], op, 'op'));
      if (voce.tipo === 'scelta') posto.append(scelta(voce.scelte, valore, 'valore'));
      else if (voce.tipo !== 'sino') posto.append(casella(valore, 'valore', voce.tipo === 'numero' ? '0' : 'testo', voce.tipo === 'numero' ? 'number' : 'text'));
    };
    campo.addEventListener('change', () => disegna());
    disegna(c.op, c.valore);
    listaCondizioni.append(riga(campo, posto));
    ridisegnaAiuti();
  };

  // ---- azioni
  const scegliPersona = (a, conEsterni) => {
    const d = dominio();
    const opzioni = [
      ...(conEsterni ? d.esterni.map((x) => [x.ruolo, x.etichetta]) : []),
      ...d.interni.map((x) => [x.ruolo, x.etichetta]),
      ['utente', 'Una persona precisa'],
      ...(conEsterni ? [['indirizzo', 'Un indirizzo email']] : []),
    ];
    const chi = scelta(opzioni, a.a, 'a');
    const posto = crea('span', { class: 'au-riga-valore' });
    const disegna = () => {
      posto.replaceChildren();
      if (chi.value === 'utente') posto.append(scelta(DATI.utenti.map((u) => [u.id, u.nome]), a.utente, 'utente'));
      if (chi.value === 'indirizzo') posto.append(casella(a.indirizzo, 'indirizzo', 'nome@azienda.it', 'email'));
    };
    chi.addEventListener('change', disegna);
    disegna();
    return [chi, posto];
  };
  const DISEGNA = {
    email: (a, d) => {
      if (!d.modelli.length) {
        return [crea('span', { class: 'au-tenue', textContent: `Non c'è ancora un modello per: ${d.nome}. ` }),
          crea('a', { class: 'ui-link', href: `${form.dataset.nuovoModello}?dominio=${eventoDi(evento.value).dominio}`, target: '_blank', textContent: 'Crealo in una nuova scheda' })];
      }
      return [crea('span', { textContent: 'Manda' }), scelta(d.modelli.map((m) => [m.codice, m.nome]), a.modello, 'modello'), crea('span', { textContent: 'a' }), ...scegliPersona(a, true)];
    },
    attivita: (a) => [crea('span', { textContent: 'Dai a' }), ...scegliPersona(a, false),
      scelta(DATI.tipi.map((t) => [t.id, t.nome]), a.tipo_attivita, 'tipo_attivita'),
      casella(a.testo, 'testo', 'Che cosa deve fare'), crea('span', { textContent: 'entro giorni' }), casella(a.giorni ?? 0, 'giorni', '0', 'number')],
    nota: (a) => [crea('span', { textContent: 'Scrivi la nota' }), casella(a.testo, 'testo', 'Testo della nota')],
    assegna: (a) => [crea('span', { textContent: 'Assegna a' }), scelta(DATI.utenti.map((u) => [u.id, u.nome]), a.utente, 'utente')],
    campo: (a, d) => {
      const campo = scelta(d.modificabili.map((m) => [m.nome, m.etichetta]), a.campo, 'campo');
      const posto = crea('span');
      const disegna = () => {
        const m = d.modificabili.find((x) => x.nome === campo.value);
        posto.replaceChildren(m && m.scelte.length ? scelta(m.scelte, a.valore, 'valore')
          : m && m.tipo === 'sino' ? scelta([['1', 'Sì'], ['0', 'No']], a.valore, 'valore') : casella(a.valore || '', 'valore', 'Valore'));
      };
      campo.addEventListener('change', disegna);
      disegna();
      return [crea('span', { textContent: 'Metti' }), campo, crea('span', { textContent: 'a' }), posto];
    },
    bottone: (a, d) => [crea('span', { textContent: 'Premi' }), scelta(d.bottoni.map((b) => [b.nome, b.etichetta]), a.bottone, 'bottone')],
    webhook: (a) => [crea('span', { textContent: 'Chiama' }), casella(a.url || '', 'url', 'https://…'), casella(a.segreto || '', 'segreto', 'Segreto per la firma (facoltativo)')],
  };
  const aggiungiAzione = (a) => {
    const d = dominio();
    if (!d) { evento.focus(); return; }
    if (a.tipo === 'assegna' && !d.assegna) { window.uiToast('Questo tipo di record non si assegna'); return; }
    if (a.tipo === 'campo' && !d.modificabili.length) { window.uiToast('Questo tipo di record non ha campi da cambiare'); return; }
    if (a.tipo === 'bottone' && !d.bottoni.length) { window.uiToast('Questo tipo di record non ha bottoni'); return; }
    const r = riga(...DISEGNA[a.tipo](a, d));
    r.dataset.tipo = a.tipo;
    listaAzioni.append(r);
    ridisegnaAiuti();
  };

  const ridisegnaAiuti = () => {
    const d = dominio();
    q('[data-c-sempre]').hidden = listaCondizioni.children.length > 0;
    q('[data-c-aggiungi-condizione]').hidden = !d || !d.condizioni.length;
    q('[data-c-campi]').textContent = d ? `Nei testi puoi usare: ${d.campi.map((c) => `{{ ${c.nome} }}`).join('  ')}` : '';
  };
  const quandoCambia = (primo) => {
    const e = eventoDi(evento.value);
    const riga_ = q('[data-c-giorni-riga]');
    riga_.hidden = !(e && e.giorni);
    giorni.required = Boolean(e && e.giorni);
    if (e && e.giorni) {
      const [prima, dopo] = e.giorni.split('{n}');
      q('[data-c-giorni-prima]').textContent = prima.trim();
      q('[data-c-giorni-dopo]').textContent = dopo.trim();
      if (!primo) giorni.value = e.giorni_default;
    }
    if (!primo) { listaCondizioni.replaceChildren(); listaAzioni.replaceChildren(); }
    ridisegnaAiuti();
  };

  // un modello creato in un'altra scheda compare al ritorno, e la regola scritta fin qui resta
  window.addEventListener('focus', async () => {
    const r = await fetch(form.dataset.elencoModelli, { credentials: 'same-origin' });
    if (!r.ok) return;
    const elenco = await r.json();
    Object.entries(DATI.domini).forEach(([codice, d]) => { d.modelli = elenco[codice] || []; });
    listaAzioni.querySelectorAll('[data-tipo="email"]').forEach((voce) => {
      if (voce.querySelector('[data-campo="modello"]')) return;
      const nuova = riga(...DISEGNA.email({}, dominio()));
      nuova.dataset.tipo = 'email';
      voce.replaceWith(nuova);
    });
  });

  // ---- avvio
  evento.append(crea('option', { value: '', textContent: 'Scegli che cosa deve succedere…' }));
  DATI.gruppi.forEach((g) => {
    const gruppo = crea('optgroup', { label: g.nome });
    g.eventi.forEach((e) => gruppo.append(crea('option', { value: e.codice, textContent: e.nome })));
    evento.append(gruppo);
  });
  q('[data-c-nome]').value = INIZIALE.nome || '';
  evento.value = INIZIALE.evento || '';
  giorni.value = INIZIALE.giorni ?? '';
  evento.addEventListener('change', () => quandoCambia(false));
  q('[data-c-aggiungi-condizione]').addEventListener('click', () => aggiungiCondizione());
  form.querySelectorAll('[data-c-aggiungi]').forEach((b) => b.addEventListener('click', () => aggiungiAzione({ tipo: b.dataset.cAggiungi })));
  quandoCambia(true);
  (INIZIALE.condizioni || []).forEach(aggiungiCondizione);
  (INIZIALE.azioni || []).forEach(aggiungiAzione);

  const leggi = (voce) => {
    const o = {};
    voce.querySelectorAll('[data-campo]').forEach((c) => { o[c.dataset.campo] = c.value; });
    return o;
  };
  form.addEventListener('submit', () => {
    q('[data-c-condizioni]').value = JSON.stringify([...listaCondizioni.children].map(leggi));
    q('[data-c-azioni]').value = JSON.stringify([...listaAzioni.children].map((v) => ({ tipo: v.dataset.tipo, ...leggi(v) })));
  });
})();
