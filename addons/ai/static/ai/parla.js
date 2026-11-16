/* «Parla con Ada»: tocchi e parli; la pagina capisce da sola quando hai finito (silenzio dopo la voce), trascrive,
   manda la domanda e legge la risposta un pezzo alla volta mentre si scrive. Finita la risposta riascolta per qualche
   secondo; toccando mentre Ada pensa o parla la interrompi e tocca a te.
   Stati: fermo → ascolto → trascrivo → penso → parlo → (ascolto | fermo). */
(function () {
  'use strict';

  // ---------- pezzi da leggere (pura: si prova da sola) ----------
  // Il testo della risposta (Markdown) arriva a pezzi; si leggono frasi intere, la prima corta perché la voce parta
  // subito. Codice e tabelle non si leggono. Ritorna {inizio, fine} (posizioni nel testo) o {salta} o null (aspetta).
  const LUNGHEZZE = [110, 260, 300];
  const MINIMO = 25;
  function prossimoPezzo(testo, da, finito, numero) {
    let i = da;
    while (i < testo.length && /\s/.test(testo[i])) i += 1;
    if (i >= testo.length) return finito && i > da ? { salta: i } : null;
    if (testo.startsWith('```', i)) {                                    // blocco di codice: si salta tutto
      const chiusura = testo.indexOf('```', i + 3);
      if (chiusura < 0) return finito ? { salta: testo.length } : null;
      return { salta: chiusura + 3 };
    }
    if (testo[i] === '|') {                                              // riga di tabella: si salta
      const a_capo = testo.indexOf('\n', i);
      if (a_capo < 0) return finito ? { salta: testo.length } : null;
      return { salta: a_capo + 1 };
    }
    const massimo = LUNGHEZZE[Math.min(numero, LUNGHEZZE.length - 1)];
    let limite = Math.min(testo.length, i + massimo);
    const codice = testo.indexOf('```', i);
    if (codice > i && codice < limite) limite = codice;
    const tabella = testo.indexOf('\n|', i);                            // una tabella che comincia più avanti
    if (tabella >= i && tabella + 1 < limite) limite = tabella + 1;
    const finestra = testo.slice(i, limite);
    let taglio = -1;
    const fineFrase = /[.!?…:;](?=\s|$)|\n/g;
    let m;
    while ((m = fineFrase.exec(finestra))) {
      const pos = m.index + m[0].length;
      if (pos >= MINIMO || m[0] === '\n') {
        taglio = pos;
        if (numero === 0) break;                 // il primo pezzo finisce alla prima frase: la voce parte prima
      }
    }
    const tuttoArrivato = finito || limite < testo.length;
    if (taglio > 0 && (taglio < finestra.length || tuttoArrivato || /[.!?…]$/.test(finestra))) {
      if (testo.slice(i, i + taglio).trim()) return { inizio: i, fine: i + taglio };
      return { salta: i + taglio };
    }
    if (finestra.length >= massimo) {                                    // frase lunghissima: si taglia a uno spazio
      const spazio = finestra.lastIndexOf(' ');
      return { inizio: i, fine: i + (spazio > MINIMO ? spazio : finestra.length) };
    }
    if (finito || limite === codice || limite === tabella + 1) return { inizio: i, fine: limite };
    return null;
  }
  window.AdaParlaPezzi = prossimoPezzo;

  const radice = document.querySelector('[data-parla]');
  if (!radice) return;

  // ---------- impostazioni ----------
  const cfg = radice.dataset;
  const SILENZIO_MS = Number(cfg.silenzio) || 1300;
  const ASCOLTO_DOPO_MS = Number(cfg.ascoltoDopo || 6000);
  const SENZA_VOCE_MS = 8000;              // al primo tocco: se non parli entro 8 s si ferma
  const VOCE_MINIMA_MS = 250;              // tanta voce di fila per dire «ha parlato»
  const VOCE_DA_INVIARE_MS = 150;          // sotto, niente invio: Whisper sul silenzio si inventa frasi
  const REGISTRAZIONE_MAX_MS = 60000;
  const PARLATO_MAX_S = 30;                // poi Ada si ferma: il resto è nella chat
  const IN_ANTICIPO = 2;                   // pezzi sintetizzati mentre uno suona
  const csrf = radice.querySelector('[name=csrfmiddlewaretoken]').value;

  const stato_el = radice.querySelector('[data-pa-stato]');
  const detto_el = radice.querySelector('[data-pa-detto]');
  const risposta_el = radice.querySelector('[data-pa-risposta]');
  const tocco = radice.querySelector('[data-pa-tocco]');
  const tela = radice.querySelector('.pa-cerchio');
  const ETICHETTE = { fermo: 'Tocca e parla', ascolto: 'Ti ascolto…', trascrivo: 'Un attimo…', penso: 'Un attimo…', parlo: 'Ada' };

  let stato = 'fermo';
  let conversazione = cfg.conversazione || '';
  let contesto = null, analizzatore = null, livello = 0;
  let microfono = null, sorgenteMic = null;
  let blocco = null;                       // wake lock dello schermo
  let reg = null;                          // registrazione in corso
  let turno = null;                        // risposta in corso
  let sentito = '';                        // quanto della risposta interrotta l'utente ha sentito

  function imposta(nuovo, messaggio) {
    stato = nuovo;
    radice.dataset.stato = nuovo;
    stato_el.textContent = messaggio || ETICHETTE[nuovo];
    tocco.setAttribute('aria-label', nuovo === 'fermo' ? 'Parla' : nuovo === 'ascolto' ? 'Ho finito' : 'Interrompi');
    if (nuovo === 'fermo') { liberaMicrofono(); rilasciaSchermo(); } else { tieniSchermo(); }
  }

  function mostra(el, testo) {
    el.hidden = !testo;
    el.textContent = testo || '';
  }

  // ---------- audio e schermo ----------
  function audio() {
    if (!contesto) {
      const AC = window.AudioContext || window.webkitAudioContext;
      contesto = new AC();
      analizzatore = contesto.createAnalyser();
      analizzatore.fftSize = 1024;
    }
    if (contesto.state === 'suspended') contesto.resume();          // sblocco dopo un tocco (iOS, Chrome)
    return contesto;
  }

  async function apriMicrofono() {
    if (microfono) return microfono;
    if (!navigator.mediaDevices || !window.MediaRecorder) throw new Error('Il browser non permette di usare il microfono su questa pagina (serve https).');
    try {
      microfono = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    } catch (e) {
      throw new Error(e && e.name === 'NotAllowedError' ? 'Il microfono non è permesso: abilitalo nelle impostazioni del browser.' : 'Microfono non disponibile.');
    }
    sorgenteMic = audio().createMediaStreamSource(microfono);
    return microfono;
  }

  function liberaMicrofono() {
    if (sorgenteMic) { try { sorgenteMic.disconnect(); } catch (e) { /* già staccato */ } sorgenteMic = null; }
    if (microfono) { microfono.getTracks().forEach((t) => t.stop()); microfono = null; }
  }

  async function tieniSchermo() {
    if (blocco || !('wakeLock' in navigator)) return;
    try { blocco = await navigator.wakeLock.request('screen'); blocco.addEventListener('release', () => { blocco = null; }); } catch (e) { /* non concesso */ }
  }
  function rilasciaSchermo() { if (blocco) { blocco.release().catch(() => {}); blocco = null; } }

  // ---------- ascolto con fine automatica ----------
  function tipoRegistrazione() {
    for (const t of ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4', 'audio/webm']) {
      if (window.MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) return t;
    }
    return '';
  }

  async function ascolta(attesaMassima) {
    try { await apriMicrofono(); } catch (e) { imposta('fermo', e.message); return; }
    const tipo = tipoRegistrazione();
    const registratore = tipo ? new MediaRecorder(microfono, { mimeType: tipo }) : new MediaRecorder(microfono);
    const pezzi = [];
    const misura = audio().createAnalyser();
    misura.fftSize = 1024;
    sorgenteMic.connect(misura);
    reg = { registratore, misura, rumore: 0, voceMs: 0, sentita: false, voceTotaleMs: 0, inizio: Date.now(),
            silenzioDa: 0, ultimo: Date.now(), annullata: false, attesa: attesaMassima };
    registratore.addEventListener('dataavailable', (e) => { if (e.data.size) pezzi.push(e.data); });
    registratore.addEventListener('stop', () => {
      try { sorgenteMic && sorgenteMic.disconnect(misura); } catch (e) { /* già staccato */ }
      const r = reg; reg = null;
      if (r.annullata) return;
      if (!r.sentita || r.voceTotaleMs < VOCE_DA_INVIARE_MS) {
        imposta('fermo', r.voceTotaleMs ? 'Non ho capito, tocca e riprova' : undefined);
        return;
      }
      trascrivi(new Blob(pezzi, { type: registratore.mimeType || tipo || 'audio/webm' }));
    });
    registratore.start(250);
    imposta('ascolto');
    misuraVoce();
  }

  function misuraVoce() {
    const r = reg;
    if (!r || r.registratore.state !== 'recording') return;
    const campioni = new Float32Array(r.misura.fftSize);
    r.misura.getFloatTimeDomainData(campioni);
    let somma = 0;
    for (let k = 0; k < campioni.length; k += 1) somma += campioni[k] * campioni[k];
    const rms = Math.sqrt(somma / campioni.length);
    livello = Math.min(1, rms * 8);
    const adesso = Date.now(), passo = adesso - r.ultimo;
    r.ultimo = adesso;
    const trascorso = adesso - r.inizio;
    if (trascorso < 300 && !r.sentita) r.rumore = Math.max(r.rumore, rms);      // il rumore di fondo dei primi istanti
    else if (!r.sentita) r.rumore = r.rumore * 0.95 + rms * 0.05;
    const soglia = Math.max(0.02, r.rumore * 3);
    if (rms > soglia && trascorso >= 300) {
      r.voceMs += passo; r.voceTotaleMs += passo; r.silenzioDa = 0;
      if (r.voceMs >= VOCE_MINIMA_MS) r.sentita = true;
    } else {
      r.voceMs = 0;
      if (r.sentita && !r.silenzioDa) r.silenzioDa = adesso;
    }
    if ((r.sentita && r.silenzioDa && adesso - r.silenzioDa >= SILENZIO_MS) || trascorso >= REGISTRAZIONE_MAX_MS
        || (!r.sentita && trascorso >= r.attesa)) {
      r.registratore.stop();
      return;
    }
    setTimeout(misuraVoce, 50);
  }

  function smettiDiAscoltare(annulla) {
    if (!reg) return;
    reg.annullata = annulla;
    if (reg.registratore.state === 'recording') reg.registratore.stop();
  }

  async function trascrivi(blob) {
    imposta('trascrivo');
    const dati = new FormData();
    dati.append('audio', blob, 'voce.' + ((blob.type.split('/')[1] || 'webm').split(';')[0]));
    try {
      const r = await fetch(cfg.ascolta, { method: 'POST', body: dati, headers: { 'X-CSRFToken': csrf } });
      const j = await r.json();
      if (!r.ok) throw new Error(j.errore || 'Non sono riuscita a capire.');
      if (!j.testo) { imposta('fermo', 'Non ho capito, tocca e riprova'); return; }
      mostra(detto_el, j.testo);
      mostra(risposta_el, '');
      chiedi(j.testo);
    } catch (e) {
      imposta('fermo', e.message || 'Errore di rete, riprova');
    }
  }

  // ---------- domanda e risposta ----------
  async function chiedi(testo) {
    imposta('penso');
    const dati = new FormData();
    dati.append('testo', testo);
    if (conversazione) dati.append('conversazione', conversazione);
    if (sentito) dati.append('sentito', sentito);
    sentito = '';
    let j;
    try {
      const r = await fetch(cfg.chiedi, { method: 'POST', body: dati, headers: { 'X-CSRFToken': csrf } });
      j = await r.json();
      if (!r.ok) throw new Error(j.errore || 'Non riesco a rispondere adesso.');
    } catch (e) { imposta('fermo', e.message || 'Errore di rete, riprova'); return; }
    if (String(j.conversazione) !== String(conversazione)) {
      conversazione = String(j.conversazione);
      history.replaceState(null, '', j.parla);
      radice.querySelectorAll('[data-pa-chat]').forEach((a) => { a.href = j.chat; });
    }
    segui(j);
  }

  function segui(j) {
    const t = { testo: '', letto: 0, numero: 0, finito: false, coda: [], suona: null, parlatoS: 0,
                fonte: new EventSource(j.flusso), stop: j.stop, id: j.turno, tagliato: false };
    turno = t;
    t.fonte.addEventListener('testo', (e) => {
      if (turno !== t) return;
      t.testo += JSON.parse(e.data).delta;
      mostra(risposta_el, testoVisibile(t.testo));
      prepara(t);
    });
    t.fonte.addEventListener('fine', (e) => {
      t.fonte.close();
      if (turno !== t) return;
      const dati = JSON.parse(e.data);
      if (dati.stato === 'errore') { turno = null; imposta('fermo', 'Ada non è riuscita a rispondere: riprova o apri la chat'); return; }
      if (typeof dati.testo === 'string') riallinea(t, dati.testo);
      t.finito = true;
      prepara(t);
      finePossibile(t);
    });
    t.fonte.onerror = () => { /* EventSource si ricollega da solo, riprendendo dal punto giusto */ };
  }

  // A turno chiuso il server toglie gli spazi in testa al testo: le posizioni dei pezzi non ancora chiesti si
  // spostano di conseguenza, e la coda scritta dopo l'ultima lettura arriva qui.
  function riallinea(t, finale) {
    const spostamento = t.testo.length - t.testo.replace(/^\s+/, '').length;
    t.testo = finale;
    t.letto = Math.max(0, t.letto - spostamento);
    if (spostamento) t.coda.forEach((p) => { if (!p.audio) { p.inizio = Math.max(0, p.inizio - spostamento); p.fine -= spostamento; } });
    mostra(risposta_el, testoVisibile(t.testo));
  }

  function testoVisibile(testo) {
    const pulito = testo.replace(/```[\s\S]*?(```|$)/g, ' ').replace(/^\|.*$/gm, '').replace(/[*_#>`]/g, '')
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\s+/g, ' ').trim();
    return pulito.length > 320 ? '…' + pulito.slice(-320) : pulito;
  }

  function prepara(t) {
    if (t.tagliato) return;
    for (;;) {
      const p = prossimoPezzo(t.testo, t.letto, t.finito, t.numero);
      if (!p) break;
      if (p.salta !== undefined) { t.letto = p.salta; continue; }
      t.letto = p.fine;
      t.numero += 1;
      t.coda.push({ inizio: p.inizio, fine: p.fine, testo: t.testo.slice(p.inizio, p.fine), audio: null });
    }
    pompa(t);
    if (!t.suona) suonaProssimo(t);
  }

  function pompa(t) {               // al massimo IN_ANTICIPO sintesi in corso o pronte non ancora suonate
    let pronte = t.coda.filter((p) => p.audio).length;
    for (const p of t.coda) {
      if (pronte >= IN_ANTICIPO) break;
      if (p.audio) continue;
      p.audio = scarica(t, p);
      pronte += 1;
    }
  }

  async function scarica(t, p) {
    const url = cfg.audio.replace('/0/0-1/', `/${t.id}/${p.inizio}-${p.fine}/`);
    const r = await fetch(url);
    if (r.status === 204) return null;
    if (!r.ok) throw new Error('lettura non riuscita');
    return audio().decodeAudioData(await r.arrayBuffer());
  }

  async function suonaProssimo(t) {
    if (turno !== t || t.suona || !t.coda.length) { finePossibile(t); return; }
    const p = t.coda[0];
    if (!p.audio) pompa(t);
    t.suona = p;
    let buffer = null;
    try { buffer = await p.audio; } catch (e) { buffer = null; }
    if (turno !== t) return;
    t.coda.shift();
    pompa(t);
    if (!buffer) { t.suona = null; suonaProssimo(t); return; }
    if (stato !== 'parlo') imposta('parlo');
    const sorgente = audio().createBufferSource();
    sorgente.buffer = buffer;
    sorgente.connect(analizzatore);
    analizzatore.connect(audio().destination);
    p.sorgente = sorgente;
    p.partito = audio().currentTime;
    sorgente.onended = () => {
      if (turno !== t || t.suona !== p) return;
      t.parlatoS += buffer.duration;
      p.finito = true;
      t.sentito = (t.sentito || '') + p.testo;
      t.suona = null;
      if (t.parlatoS >= PARLATO_MAX_S && (t.coda.length || !t.finito)) {
        t.tagliato = true; t.coda = [];
        mostra(risposta_el, 'La risposta continua nella chat: tocca «Apri nella chat» per leggerla tutta.');
      }
      suonaProssimo(t);
    };
    sorgente.start();
  }

  function finePossibile(t) {
    if (turno !== t || t.suona || t.coda.length || !(t.finito || t.tagliato)) return;
    turno = null;
    if (ASCOLTO_DOPO_MS > 0) ascolta(ASCOLTO_DOPO_MS);
    else imposta('fermo');
  }

  function interrompi() {
    const t = turno;
    if (!t) return;
    turno = null;
    try { t.fonte.close(); } catch (e) { /* già chiusa */ }
    let parte = t.sentito || '';
    if (t.suona && t.suona.sorgente) {
      const p = t.suona;
      const quota = Math.min(1, (audio().currentTime - p.partito) / (p.sorgente.buffer.duration || 1));
      parte += p.testo.slice(0, Math.round(p.testo.length * quota));
      p.sorgente.onended = null;
      try { p.sorgente.stop(); } catch (e) { /* già finita */ }
    }
    sentito = parte.trim() || (t.testo ? '(niente: mi hai interrotto prima che parlassi)' : '');
    if (!t.finito) fetch(t.stop, { method: 'POST', headers: { 'X-CSRFToken': csrf } }).catch(() => {});
  }

  // ---------- tocchi ----------
  tocco.addEventListener('click', () => {
    audio();
    if (stato === 'fermo') { mostra(risposta_el, ''); ascolta(SENZA_VOCE_MS); }
    else if (stato === 'ascolto') {
      if (reg && reg.sentita) reg.registratore.stop();          // ho finito: si manda subito
      else { smettiDiAscoltare(true); imposta('fermo'); }
    } else if (stato === 'penso' || stato === 'parlo') { interrompi(); ascolta(SENZA_VOCE_MS); }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { smettiDiAscoltare(true); interrompi(); imposta('fermo'); }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && stato === 'ascolto') { smettiDiAscoltare(true); imposta('fermo'); }
    if (!document.hidden && stato !== 'fermo') tieniSchermo();
  });
  radice.querySelectorAll('[data-pa-chat]').forEach((a) => a.addEventListener('click', () => {
    try { sessionStorage.setItem('ai-parla-vista', '1'); } catch (e) { /* senza storage: pazienza */ }
    smettiDiAscoltare(true); interrompi();
  }));
  try { sessionStorage.setItem('ai-parla-vista', '1'); } catch (e) { /* idem */ }

  // ---------- cerchio ----------
  const ctx = tela.getContext && tela.getContext('2d');
  const piano = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function colore(nome, riserva) { return getComputedStyle(document.documentElement).getPropertyValue(nome).trim() || riserva; }
  function disegna(ora) {
    if (!ctx) return;
    const lato = tela.clientWidth, dpr = window.devicePixelRatio || 1;
    if (tela.width !== lato * dpr) { tela.width = lato * dpr; tela.height = lato * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, lato, lato);
    const c = lato / 2, base = lato * 0.30;
    let liv = 0;
    if (stato === 'parlo' && analizzatore) {
      const d = new Float32Array(analizzatore.fftSize);
      analizzatore.getFloatTimeDomainData(d);
      let s = 0; for (let k = 0; k < d.length; k += 1) s += d[k] * d[k];
      liv = Math.min(1, Math.sqrt(s / d.length) * 6);
    } else if (stato === 'ascolto') liv = livello;
    const primario = colore('--ui-accent', colore('--ui-primary', '#1e3a8a'));
    ctx.lineWidth = 3;
    ctx.strokeStyle = primario;
    ctx.beginPath();
    const punti = 96;
    for (let k = 0; k <= punti; k += 1) {
      const a = (k / punti) * Math.PI * 2;
      const onda = piano ? 0 : Math.sin(a * 5 + ora / 260) * liv * 0.12 + Math.sin(a * 3 - ora / 410) * liv * 0.08;
      const r = base * (1 + liv * 0.15 + onda) + (stato === 'fermo' && !piano ? Math.sin(ora / 900) * 2 : 0);
      const x = c + Math.cos(a) * r, y = c + Math.sin(a) * r;
      if (k) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    }
    ctx.stroke();
    if (stato === 'penso' || stato === 'trascrivo') {               // un punto che gira: sto pensando
      const a = piano ? 0 : ora / 380;
      ctx.fillStyle = primario;
      ctx.beginPath();
      ctx.arc(c + Math.cos(a) * base, c + Math.sin(a) * base, 6, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(disegna);
  }
  requestAnimationFrame(disegna);
  imposta('fermo');
})();
