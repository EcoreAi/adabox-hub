// Studio: editor di una vista. Lo stato arriva dal server (json_script), si modifica qui e si invia come JSON.
(function () {
  const stato = JSON.parse(document.getElementById('studio-stato').textContent);
  const dati = JSON.parse(JSON.stringify(stato.attuali));
  dati.etichette = dati.etichette || {};
  const nomi = {};
  Object.values(stato.disponibili).forEach((voci) => voci.forEach(([n, e]) => { if (!(n in nomi)) nomi[n] = e; }));
  const etichetta = (n) => dati.etichette[n.replace(/^-/, '')] || nomi[n.replace(/^-/, '')] || n;

  function el(tag, attributi = {}, ...figli) {
    const e = document.createElement(tag);
    Object.entries(attributi).forEach(([k, v]) => {
      if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (k === 'class') e.className = v;
      else e.setAttribute(k, v);
    });
    figli.flat().forEach((f) => e.append(f));
    return e;
  }
  const bottone = (testo, titolo, azione) => el('button', { type: 'button', title: titolo, 'aria-label': titolo, onclick: azione }, testo);
  const sposta = (lista, da, a) => { if (a < 0 || a >= lista.length) return; lista.splice(a, 0, lista.splice(da, 1)[0]); };

  // ---- Schede ----
  const schede = document.querySelectorAll('[data-scheda]');
  function mostra(nome) {
    schede.forEach((s) => s.classList.toggle('is-active', s.dataset.scheda === nome));
    document.querySelectorAll('[data-pannello]').forEach((p) => { p.hidden = p.dataset.pannello !== nome; });
  }
  schede.forEach((s) => s.addEventListener('click', (ev) => { ev.preventDefault(); mostra(s.dataset.scheda); history.replaceState(null, '', `#${s.dataset.scheda}`); }));
  if (location.hash && document.querySelector(`[data-scheda="${location.hash.slice(1)}"]`)) mostra(location.hash.slice(1));

  // ---- Elenchi ordinabili (colonne, filtri, ...) ----
  function elenco(contenitore) {
    const chiave = contenitore.dataset.elenco;
    const conDirezione = contenitore.hasAttribute('data-direzione');
    const disponibili = stato.disponibili[chiave] || [];
    let trascinato = null;
    function disegna() {
      const valori = dati[chiave];
      const usati = new Set(valori.map((v) => v.replace(/^-/, '')));
      const corpo = el('div', { class: 'studio-elenco' });
      valori.forEach((v, i) => {
        const chip = el('span', { class: 'studio-chip', draggable: 'true' }, etichetta(v));
        if (conDirezione) {
          chip.append(bottone(v.startsWith('-') ? '↓' : '↑', 'Inverti la direzione', () => { valori[i] = v.startsWith('-') ? v.slice(1) : `-${v}`; disegna(); }));
        }
        chip.append(bottone('◀', 'Sposta prima', () => { sposta(valori, i, i - 1); disegna(); }),
          bottone('▶', 'Sposta dopo', () => { sposta(valori, i, i + 1); disegna(); }),
          bottone('✕', 'Togli', () => { valori.splice(i, 1); disegna(); }));
        chip.addEventListener('dragstart', () => { trascinato = i; chip.classList.add('is-trascinato'); });
        chip.addEventListener('dragend', () => chip.classList.remove('is-trascinato'));
        chip.addEventListener('dragover', (ev) => { ev.preventDefault(); chip.classList.add('is-sopra'); });
        chip.addEventListener('dragleave', () => chip.classList.remove('is-sopra'));
        chip.addEventListener('drop', (ev) => { ev.preventDefault(); if (trascinato !== null) { sposta(valori, trascinato, i); trascinato = null; disegna(); } });
        corpo.append(chip);
      });
      const liberi = disponibili.filter(([n]) => !usati.has(n));
      if (liberi.length) {
        const scelta = el('select', { class: 'ui-input studio-aggiungi', 'aria-label': 'Aggiungi' },
          el('option', { value: '' }, '+ Aggiungi…'), liberi.map(([n, e]) => el('option', { value: n }, e)));
        scelta.addEventListener('change', () => { if (scelta.value) { valori.push(scelta.value); disegna(); } });
        corpo.append(scelta);
      }
      contenitore.replaceChildren(corpo);
    }
    disegna();
  }
  document.querySelectorAll('[data-elenco]').forEach(elenco);

  const perPagina = document.querySelector('[data-per-pagina]');
  if (perPagina) {
    perPagina.value = dati.per_page;
    perPagina.addEventListener('input', () => { dati.per_page = parseInt(perPagina.value, 10) || dati.per_page; });
  }

  // ---- Layout del form ----
  const layout = document.querySelector('[data-layout]');
  const avviso = document.querySelector('[data-mancanti]');
  let presa = null;                                   // {s, r, i} del campo trascinato
  function disegnaLayout() {
    if (!layout) return;
    const usati = new Set(dati.form_layout.flatMap(([, righe]) => righe.flat()));
    const liberi = stato.disponibili.form.filter(([n]) => !usati.has(n));
    const mancanti = stato.obbligatori.filter((n) => !usati.has(n));
    avviso.hidden = !mancanti.length;
    avviso.textContent = mancanti.length ? `Campi obbligatori da collocare: ${mancanti.map(etichetta).join(', ')}.` : '';
    const sezioni = dati.form_layout.map(([titolo, righe], s) => {
      const nome = el('input', { class: 'ui-input', value: titolo, placeholder: 'Titolo della sezione', 'aria-label': 'Titolo della sezione' });
      nome.addEventListener('input', () => { dati.form_layout[s][0] = nome.value; });
      const testa = el('div', { class: 'studio-sezione-testa' }, nome, el('span', { class: 'studio-azioni' },
        bottone('↑', 'Sezione su', () => { sposta(dati.form_layout, s, s - 1); disegnaLayout(); }),
        bottone('↓', 'Sezione giù', () => { sposta(dati.form_layout, s, s + 1); disegnaLayout(); }),
        bottone('✕', 'Elimina la sezione', () => { dati.form_layout.splice(s, 1); disegnaLayout(); })));
      const corpoRighe = righe.map((riga, r) => {
        const chips = riga.map((campo, i) => {
          const chip = el('span', { class: `studio-chip${stato.obbligatori.includes(campo) ? ' is-obbligatorio' : ''}`, draggable: 'true' }, etichetta(campo),
            bottone('◀', 'Sposta prima', () => { sposta(riga, i, i - 1); disegnaLayout(); }),
            bottone('▶', 'Sposta dopo', () => { sposta(riga, i, i + 1); disegnaLayout(); }),
            bottone('✕', 'Togli dal form', () => { riga.splice(i, 1); disegnaLayout(); }));
          chip.addEventListener('dragstart', () => { presa = { s, r, i }; chip.classList.add('is-trascinato'); });
          chip.addEventListener('dragend', () => chip.classList.remove('is-trascinato'));
          return chip;
        });
        const aggiungi = el('select', { class: 'ui-input studio-aggiungi', 'aria-label': 'Aggiungi un campo alla riga' },
          el('option', { value: '' }, '+ Campo…'), liberi.map(([n, e]) => el('option', { value: n }, e)));
        aggiungi.addEventListener('change', () => { if (aggiungi.value) { riga.push(aggiungi.value); disegnaLayout(); } });
        const contenitore = el('div', { class: 'studio-riga' }, el('div', { class: 'studio-elenco' }, chips, liberi.length ? aggiungi : ''),
          el('span', { class: 'studio-azioni' },
            bottone('↑', 'Riga su', () => { sposta(righe, r, r - 1); disegnaLayout(); }),
            bottone('↓', 'Riga giù', () => { sposta(righe, r, r + 1); disegnaLayout(); }),
            bottone('✕', 'Elimina la riga', () => { righe.splice(r, 1); disegnaLayout(); })));
        contenitore.addEventListener('dragover', (ev) => { ev.preventDefault(); contenitore.classList.add('is-sopra'); });
        contenitore.addEventListener('dragleave', () => contenitore.classList.remove('is-sopra'));
        contenitore.addEventListener('drop', (ev) => {
          ev.preventDefault();
          if (!presa) return;
          const origine = dati.form_layout[presa.s][1][presa.r];
          const [campo] = origine.splice(presa.i, 1);
          riga.push(campo);
          presa = null;
          disegnaLayout();
        });
        return contenitore;
      });
      const nuovaRiga = el('button', { type: 'button', class: 'ui-btn ui-btn-ghost ui-btn-sm', onclick: () => { righe.push([]); disegnaLayout(); } }, '+ Riga');
      return el('div', { class: 'studio-sezione' }, testa, corpoRighe, nuovaRiga);
    });
    layout.replaceChildren(...sezioni);
  }
  const nuovaSezione = document.querySelector('[data-nuova-sezione]');
  if (nuovaSezione) nuovaSezione.addEventListener('click', () => { dati.form_layout.push(['Nuova sezione', [[]]]); disegnaLayout(); });
  disegnaLayout();

  // ---- Etichette ----
  const tabellaEtichette = document.querySelector('[data-etichette]');
  if (tabellaEtichette) {
    Object.entries(stato.etichette_base).forEach(([n, base]) => {
      const campo = el('input', { class: 'ui-input', value: dati.etichette[n] || '', placeholder: base, 'aria-label': `Etichetta di ${base}` });
      campo.addEventListener('input', () => {
        if (campo.value.trim()) dati.etichette[n] = campo.value; else delete dati.etichette[n];
      });
      tabellaEtichette.append(el('tr', {}, el('td', { class: 'ui-help' }, n), el('td', {}, base), el('td', {}, campo)));
    });
  }

  // ---- Invio ----
  document.getElementById('studio-form').addEventListener('submit', () => {
    dati.form_layout = dati.form_layout.map(([t, righe]) => [t, righe.filter((r) => r.length)]);
    document.querySelector('[data-studio-dati]').value = JSON.stringify(dati);
  });
})();
