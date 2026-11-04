// Ctrl+K da qualsiasi pagina (si carica solo se il modulo è attivo) e attività per la presenza nella testata.
(function () {
  if (window.dsPalette) return;
  const script = document.currentScript;
  const urlPalette = script && script.dataset.palette;
  let ultimaAttivita = Date.now();
  ['keydown', 'pointerdown', 'pointermove', 'scroll'].forEach((e) => document.addEventListener(e, () => { ultimaAttivita = Date.now(); }, { passive: true, capture: true }));
  document.body.addEventListener('htmx:configRequest', (ev) => {
    if (String(ev.detail.path).includes('/discuss/contatore/')) {
      ev.detail.parameters.attivo = document.visibilityState === 'visible' && Date.now() - ultimaAttivita < 300000 ? '1' : '0';
    }
  });

  let sfondo, input, elenco, voci = [], scelta = 0, timer;
  const SEGNI = { persona: '@', canale: '#', cerca: '⌕', posta: '✉' };
  function costruisci() {
    sfondo = document.createElement('div');
    sfondo.className = 'dsp-sfondo';
    sfondo.hidden = true;
    sfondo.innerHTML = '<div class="dsp-finestra" role="dialog" aria-label="Cerca o vai a"><input class="dsp-input" type="search" placeholder="Cerca una persona, un canale o un messaggio…" aria-label="Cerca"><div class="dsp-elenco" role="listbox"></div><div class="dsp-piede"><span><kbd>↑</kbd> <kbd>↓</kbd> scegli</span><span><kbd>Invio</kbd> apri</span><span><kbd>Esc</kbd> chiudi</span></div></div>';
    document.body.appendChild(sfondo);
    input = sfondo.querySelector('input');
    elenco = sfondo.querySelector('.dsp-elenco');
    sfondo.addEventListener('pointerdown', (ev) => { if (ev.target === sfondo) chiudi(); });
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(carica, 120); });
    input.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        if (voci.length) { scelta = (scelta + (ev.key === 'ArrowDown' ? 1 : -1) + voci.length) % voci.length; disegna(); }
      } else if (ev.key === 'Enter') {
        ev.preventDefault();
        if (voci[scelta]) location.href = voci[scelta].url;
      } else if (ev.key === 'Escape') { chiudi(); }
    });
  }
  function disegna() {
    elenco.textContent = '';
    if (!voci.length) { const v = document.createElement('div'); v.className = 'dsp-vuoto'; v.textContent = 'Nessun risultato'; elenco.appendChild(v); return; }
    voci.forEach((voce, i) => {
      const a = document.createElement('a');
      a.className = 'dsp-voce' + (i === scelta ? ' is-scelta' : '');
      a.href = voce.url;
      a.setAttribute('role', 'option');
      const segno = document.createElement('span'); segno.className = 'dsp-segno'; segno.textContent = SEGNI[voce.tipo] || '•';
      const testo = document.createElement('span'); testo.textContent = voce.testo;
      a.append(segno, testo);
      if (voce.dettaglio) { const d = document.createElement('small'); d.textContent = voce.dettaglio; a.appendChild(d); }
      elenco.appendChild(a);
      if (i === scelta) a.scrollIntoView({ block: 'nearest' });
    });
  }
  async function carica() {
    const q = input.value.trim();
    try {
      const r = await fetch(`${urlPalette}?q=${encodeURIComponent(q)}`, { headers: { Accept: 'application/json' } });
      if (!r.ok || input.value.trim() !== q) return;
      voci = (await r.json()).voci; scelta = 0; disegna();
    } catch (e) { /* rete assente: la palette resta com'è */ }
  }
  function apri() { if (!sfondo) costruisci(); sfondo.hidden = false; input.value = ''; input.focus(); carica(); }
  function chiudi() { if (sfondo) sfondo.hidden = true; }
  // presenza accanto alle persone del chatter dei record
  const urlPresenze = script && script.dataset.presenze;
  async function presenze() {
    const avatar = [...document.querySelectorAll('[data-presenza-utente]')];
    const id = [...new Set(avatar.map((a) => a.dataset.presenzaUtente))];
    if (!id.length || !urlPresenze) return;
    try {
      const r = await fetch(`${urlPresenze}?id=${id.join(',')}`);
      if (!r.ok) return;
      const { stati } = await r.json();
      avatar.forEach((a) => {
        const s = stati[a.dataset.presenzaUtente];
        if (!s) return;
        let punto = a.querySelector('.dsp-presenza');
        if (!punto) { punto = document.createElement('span'); a.appendChild(punto); }
        punto.className = `dsp-presenza is-${s.stato}`;
        punto.title = s.etichetta;
      });
    } catch (e) { /* senza rete nessun pallino */ }
  }
  presenze();
  document.body.addEventListener('htmx:afterSettle', () => { clearTimeout(presenze.t); presenze.t = setTimeout(presenze, 200); });

  // finestre caricate dal server («Condividi» sui record, «Crea attività» sui messaggi)
  async function apriFinestra(url) {
    const r = await fetch(url, { headers: { 'HX-Request': 'true' } });
    if (!r.ok) return;
    document.getElementById('ds-finestra')?.remove();
    const d = document.createElement('dialog');
    d.className = 'ds-dialogo'; d.id = 'ds-finestra';
    d.innerHTML = await r.text();
    document.body.appendChild(d);
    if (window.htmx) htmx.process(d);
    d.showModal();
    d.addEventListener('close', () => d.remove());
  }
  document.addEventListener('click', (ev) => {
    const apre = ev.target.closest('[data-finestra], [data-lavoro]');
    if (apre) { ev.preventDefault(); apriFinestra(apre.dataset.finestra || apre.dataset.lavoro); return; }
    if (ev.target.closest('#ds-finestra [data-chiudi]')) ev.target.closest('dialog').close();
  });
  document.addEventListener('input', (ev) => {
    const filtro = ev.target.closest('#ds-finestra [data-scelta-filtro]');
    if (!filtro) return;
    const q = filtro.value.trim().toLowerCase();
    filtro.closest('[data-scelta]').querySelectorAll('.ds-scelta-voce').forEach((v) => { v.hidden = q && !v.dataset.nome.includes(q); });
  });
  document.body.addEventListener('htmx:afterRequest', (ev) => {
    const form = ev.detail.elt;
    if (form && form.closest && form.closest('#ds-finestra') && form.matches('[data-chiudi-dopo]') && ev.detail.successful) form.closest('dialog').close();
  });

  // squillo: arriva in tempo reale in Comunicazioni, con il battito della testata altrove
  const rifiutati = () => { try { return JSON.parse(sessionStorage.getItem('ds-rifiutati') || '[]'); } catch (e) { return []; } };
  const aperti = new Map();
  function togliSquillo(token) { const el = aperti.get(token); if (el) { el.remove(); aperti.delete(token); } }
  function squilla(token, nome, url, video) {
    if (aperti.has(token) || rifiutati().includes(token)) return;
    const el = document.createElement('div');
    el.className = 'dsp-squillo'; el.setAttribute('role', 'alertdialog');
    const t = document.createElement('strong'); t.textContent = nome;
    const s = document.createElement('span'); s.textContent = video ? 'ti sta videochiamando' : 'ti sta chiamando';
    const azioni = document.createElement('div'); azioni.className = 'dsp-squillo-azioni';
    const si = document.createElement('a'); si.href = url; si.target = '_blank'; si.rel = 'noopener'; si.textContent = 'Rispondi';
    const no = document.createElement('button'); no.type = 'button'; no.textContent = 'Rifiuta';
    const chiudi2 = () => { try { sessionStorage.setItem('ds-rifiutati', JSON.stringify([...rifiutati(), token])); } catch (e) { /* resterà */ } togliSquillo(token); };
    si.addEventListener('click', chiudi2); no.addEventListener('click', chiudi2);
    azioni.append(si, no); el.append(t, s, azioni); document.body.appendChild(el); aperti.set(token, el);
    setTimeout(() => togliSquillo(token), 60000);
  }
  function leggiSquilli() { document.querySelectorAll('[data-ds-squillo]').forEach((e) => squilla(e.dataset.dsSquillo, e.dataset.nome, e.dataset.url, e.dataset.video === '1')); }
  leggiSquilli();
  document.body.addEventListener('htmx:afterSettle', leggiSquilli);
  window.dsSquillo = { squilla, togli: togliSquillo };

  window.dsPalette = { apri, chiudi };
  document.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k') {
      ev.preventDefault();
      if (sfondo && !sfondo.hidden) chiudi(); else apri();
    }
  });
  document.addEventListener('click', (ev) => { if (ev.target.closest('[data-palette-apri]')) apri(); });
})();
