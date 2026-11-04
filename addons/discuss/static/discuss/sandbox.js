// La sandbox: il telefono del cliente e il registro. Tutto ciò che mostra viene dal server: è ciò che è passato davvero.
(function () {
  const r = document.getElementById('sb'), $ = (id) => document.getElementById(id);
  const csrf = r.querySelector('[name=csrfmiddlewaretoken]').value;
  let dopo = 0, timer;
  const contatto = () => $('sb-contatto').value.trim();
  function fumetto(e) {
    const f = document.createElement('div');
    const dalCliente = e.verso === 'entrata';
    const nota = (!e.testo || e.testo.startsWith('[')) && !e.media;
    let classe = dalCliente ? 'is-cliente' : '';
    if (e.codice >= 400) classe = 'is-rifiuto';
    else if (dalCliente && nota) classe = 'is-nota';
    f.className = `sb-fumetto ${classe}`;
    let testo = e.testo || '';
    if (e.codice >= 400) testo = dalCliente ? `Rifiutato (${e.codice}): ${e.risposta.esito}` : `Non consegnato (${e.codice}): ${testo.slice(0, 80)}`;
    f.textContent = testo;
    if (e.risposta && e.risposta.prova === 'ripetizione') f.textContent = `Ripetizione ignorata: ${e.risposta.esito}`;
    if (e.media && e.codice < 400) {
      if (e.media.immagine) { const i = document.createElement('img'); i.src = e.media.url; i.alt = e.media.nome; i.className = 'sb-immagine'; f.prepend(i); if (testo.startsWith('[')) f.childNodes[1].remove(); } else if (e.media.audio) { const a = document.createElement('audio'); a.controls = true; a.src = e.media.url; a.className = 'sb-audio'; f.prepend(a); if (testo.startsWith('[')) f.childNodes[1].remove(); } else { f.textContent = `📎 ${e.media.nome}`; }
    }
    const ora = document.createElement('small'); ora.textContent = e.ora; f.appendChild(ora);
    $('sb-chat').appendChild(f); $('sb-chat').scrollTop = $('sb-chat').scrollHeight;
  }
  function voceRegistro(e) {
    const d = document.createElement('details'); d.className = 'sb-voce';
    const s = document.createElement('summary');
    const c = document.createElement('span'); c.className = 'sb-codice' + (e.codice >= 400 ? ' is-errore' : ''); c.textContent = e.codice;
    const t = document.createElement('span'); t.textContent = `${e.ora} ${e.verso === 'entrata' ? '→ webhook' : '← API'} · ${e.testo || ''}`;
    s.append(c, t);
    const p = document.createElement('pre'); p.textContent = JSON.stringify({ richiesta: e.richiesta, risposta: e.risposta }, null, 2);
    d.append(s, p);
    const reg = $('sb-registro'); const vuoto = reg.querySelector('p'); if (vuoto) vuoto.remove();
    reg.prepend(d);
  }
  function applica(dati) {
    dati.eventi.forEach((e) => { dopo = Math.max(dopo, e.id); if (e.contatto === contatto()) fumetto(e); voceRegistro(e); });
    const c = dati.conversazione;
    $('sb-conv').textContent = !c ? 'Nessuna conversazione aperta con questo cliente.' : `Ora risponde: ${c.gestita_da === 'ai' ? "l'AI" : 'una persona'}${c.fuori_finestra ? " · oltre le 24 ore: l'azienda non può più scrivere" : ''}`;
    if (c) $('sb-apri').href = c.url;
  }
  async function leggi() {
    clearTimeout(timer);
    try {
      const x = await fetch(`${r.dataset.eventi}?dopo=${dopo}&contatto=${encodeURIComponent(contatto())}`);
      if (x.ok) applica(await x.json());
    } catch (e) { /* si riprova */ }
    timer = setTimeout(leggi, 1500);
  }
  async function fa(valori) {
    clearTimeout(timer);
    try {
      const x = await fetch(r.dataset.azione, { method: 'POST', headers: { 'X-CSRFToken': csrf },
        body: new URLSearchParams({ contatto: contatto(), nome: $('sb-nome').value, dopo, ...valori }) });
      if (x.ok) applica(await x.json());
    } catch (e) { /* si riprova */ }
    timer = setTimeout(leggi, 800);
  }
  $('sb-scrivi').addEventListener('submit', (ev) => { ev.preventDefault(); const t = $('sb-testo').value.trim(); if (t) { fa({ fa: 'scrivi', testo: t }); $('sb-testo').value = ''; } });
  r.addEventListener('click', (ev) => {
    const s = ev.target.closest('[data-scrivi]');
    if (s) { fa({ fa: 'scrivi', testo: s.dataset.scrivi }); return; }
    const b = ev.target.closest('[data-fa]');
    if (!b) return;
    if (b.dataset.fa === 'azzera') { fa({ fa: 'azzera' }).then(() => { $('sb-chat').textContent = ''; $('sb-registro').textContent = ''; dopo = 0; }); return; }
    fa({ fa: b.dataset.fa, stato: b.dataset.stato || '' });
  });
  async function mandaFile(input, vocale) {
    const f = input.files[0];
    if (!f) return;
    const dati = new FormData();
    dati.append('fa', 'file'); dati.append('file', f); dati.append('contatto', contatto()); dati.append('nome', $('sb-nome').value); dati.append('dopo', dopo);
    if (vocale) dati.append('vocale', '1');
    if ($('sb-testo').value.trim()) { dati.append('testo', $('sb-testo').value.trim()); $('sb-testo').value = ''; }
    clearTimeout(timer);
    const x = await fetch(r.dataset.azione, { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: dati }).catch(() => null);
    if (x && x.ok) applica(await x.json());
    input.value = '';
    timer = setTimeout(leggi, 800);
  }
  $('sb-file').addEventListener('change', (ev) => mandaFile(ev.target, false));
  $('sb-vocale').addEventListener('change', (ev) => mandaFile(ev.target, true));
  $('sb-guasto').addEventListener('change', (ev) => fa({ fa: 'guasto', guasto: ev.target.value }));
  $('sb-contatto').addEventListener('change', () => { $('sb-chat').textContent = ''; dopo = 0; $('sb-registro').textContent = ''; leggi(); });
  leggi();
})();
