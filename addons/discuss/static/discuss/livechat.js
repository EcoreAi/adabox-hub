// La chat del visitatore: il token sta nel browser e riapre la stessa conversazione al ritorno sul sito.
(function () {
  const r = document.getElementById('lc'), d = r.dataset;
  const $ = (id) => document.getElementById(id);
  const chiave = `ds-lc-${d.chiave}`;
  let token = null, ultimo = 0, timer = null;
  try { token = localStorage.getItem(chiave); } catch (e) { /* senza memoria: vale per questa visita */ }
  const errore = (t) => { $('lc-errore').textContent = t || ''; $('lc-errore').hidden = !t; };
  function aggiungi(m) {
    const el = document.createElement('div'); el.className = 'lc-msg' + (m.mio ? ' is-mio' : '');
    if (!m.mio) { const n = document.createElement('small'); n.textContent = m.nome; el.appendChild(n); }
    const t = document.createElement('span'); t.textContent = m.testo; el.appendChild(t);
    const elenco = $('lc-elenco'); elenco.appendChild(el); elenco.scrollTop = elenco.scrollHeight;
  }
  function chiusa() {
    if ($('lc-scrivi').hidden && !token) return;
    $('lc-scrivi').hidden = true;
    if (!document.querySelector('.lc-avviso')) {
      const a = document.createElement('div'); a.className = 'lc-avviso'; a.textContent = 'La conversazione è stata chiusa. Grazie!';
      const nuova = document.createElement('button'); nuova.type = 'button'; nuova.textContent = 'Nuova conversazione'; nuova.style.marginTop = '6px';
      nuova.addEventListener('click', () => { try { localStorage.removeItem(chiave); } catch (e) { /* niente */ } location.reload(); });
      a.append(document.createElement('br'), nuova); $('lc-elenco').appendChild(a);
    }
    clearTimeout(timer); timer = null;
  }
  async function leggi() {
    try {
      const x = await fetch(`${d.messaggi}?dopo=${ultimo}`, { headers: { 'X-Token': token } });
      if (x.status === 403) { try { localStorage.removeItem(chiave); } catch (e) { /* niente */ } token = null; $('lc-scrivi').hidden = true; $('lc-inizio').hidden = false; return; }
      if (x.ok) {
        const dati = await x.json();
        dati.messaggi.forEach((m) => { aggiungi(m); ultimo = Math.max(ultimo, m.id); });
        $('lc-stato').textContent = dati.online ? 'Online' : "Ora non c'è nessuno online: ti rispondiamo appena possibile";
        if (dati.chiusa) { chiusa(); return; }
      }
    } catch (e) { /* senza rete si riprova */ }
    timer = setTimeout(leggi, document.hidden ? 15000 : 3000);
  }
  function inConversazione() { $('lc-inizio').hidden = true; $('lc-scrivi').hidden = false; leggi(); }
  $('lc-inizio').addEventListener('submit', async (ev) => {
    ev.preventDefault(); errore('');
    const f = ev.target, b = f.querySelector('button'); b.disabled = true;
    const dati = new URLSearchParams(new FormData(f)); dati.set('pagina', d.pagina || '');
    try {
      const x = await fetch(d.avvia, { method: 'POST', body: dati });
      const j = await x.json();
      if (!x.ok) { errore(j.errore); b.disabled = false; return; }
      token = j.token;
      try { localStorage.setItem(chiave, token); } catch (e) { /* vale per questa visita */ }
      inConversazione();
    } catch (e) { errore('Connessione assente: riprova.'); b.disabled = false; }
  });
  const scrivi = $('lc-scrivi'), area = scrivi.querySelector('textarea');
  async function manda() {
    const testo = area.value.trim();
    if (!testo) return;
    errore('');
    try {
      const x = await fetch(d.scrivi, { method: 'POST', headers: { 'X-Token': token }, body: new URLSearchParams({ testo }) });
      if (x.ok) { area.value = ''; clearTimeout(timer); leggi(); } else { errore((await x.json()).errore); }
    } catch (e) { errore('Messaggio non inviato: riprova.'); }
  }
  scrivi.addEventListener('submit', (ev) => { ev.preventDefault(); manda(); });
  area.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); manda(); } });
  if (token) inConversazione();
})();
