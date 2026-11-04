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
  window.dsPalette = { apri, chiudi };
  document.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k') {
      ev.preventDefault();
      if (sfondo && !sfondo.hidden) chiudi(); else apri();
    }
  });
  document.addEventListener('click', (ev) => { if (ev.target.closest('[data-palette-apri]')) apri(); });
})();
