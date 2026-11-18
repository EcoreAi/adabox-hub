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
  const tela = radice.querySelector('.pa-sfera');
  const tastiera = radice.querySelector('[data-pa-tastiera]');
  const scrivi = radice.querySelector('[data-pa-scrivi]');
  const ETICHETTE = { fermo: 'Tocca e parla', ascolto: 'Ti ascolto…', trascrivo: 'Un attimo…', penso: 'Un attimo…', parlo: 'Ada' };

  let stato = 'fermo';
  let conversazione = cfg.conversazione || '';
  let contesto = null, analizzatore = null, volume = null, livello = 0;
  // «senza voce» (per la riservatezza): Ada risponde solo con i sottotitoli. L'audio passa comunque per l'analizzatore,
  // quindi tempi dei sottotitoli e cubo che pulsa restano gli stessi; si azzera solo il volume. Ricordato sul dispositivo.
  let muto = false;
  try { muto = localStorage.getItem('ai-parla-muto') === '1'; } catch (e) { /* senza storage: con la voce */ }
  let microfono = null, sorgenteMic = null;
  let blocco = null;                       // wake lock dello schermo
  let reg = null;                          // registrazione in corso
  let turno = null;                        // risposta in corso
  let sentito = '';                        // quanto della risposta interrotta l'utente ha sentito

  let daTastiera = false;                  // domanda scritta: dopo la risposta non si riapre il microfono
  function imposta(nuovo, messaggio) {
    if (nuovo !== stato && (nuovo === 'ascolto' || nuovo === 'parlo') && navigator.vibrate) {
      try { navigator.vibrate(12); } catch (e) { /* non supportata */ }
    }
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
      volume = contesto.createGain();
      volume.gain.value = muto ? 0 : 1;
      analizzatore.connect(volume);
      volume.connect(contesto.destination);
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
    reg = { registratore, misura, rumore: 0, somma: 0, letture: 0, voceMs: 0, sentita: false, voceTotaleMs: 0, inizio: Date.now(),
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
    // rumore di fondo: la media dei primi istanti (non il massimo: chi parla subito non deve passare per rumore),
    // poi si adegua piano finché non si sente la voce
    if (trascorso < 300 && !r.sentita) { r.somma += rms; r.letture += 1; r.rumore = r.somma / r.letture; }
    else if (!r.sentita) r.rumore = r.rumore * 0.95 + rms * 0.05;
    const soglia = Math.max(0.015, Math.min(r.rumore * 3, 0.05));              // il tetto: la voce normale lo supera sempre
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
      svuotaSottotitoli();
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
    if (cfg.ambito) dati.append('app', cfg.ambito);             // l'app scelta in alto
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
    // conDati: la risposta poggia su dati letti (uno strumento è stato usato). Finché non lo è non si parla: una
    // risposta senza fonti può essere scartata dalla guardia del server e rifatta, e non deve essere già stata letta.
    const t = { testo: '', letto: 0, numero: 0, finito: false, coda: [], suona: null, parlatoS: 0, conDati: false,
                fonte: new EventSource(j.flusso), stop: j.stop, id: j.turno, tagliato: false };
    turno = t;
    mostraVerifica(null);
    t.fonte.addEventListener('testo', (e) => {
      if (turno !== t) return;
      t.testo += JSON.parse(e.data).delta;
      if (t.conDati) prepara(t);
    });
    t.fonte.addEventListener('avanzamento', (e) => {
      if (turno !== t || t.conDati) return;
      const voci = JSON.parse(e.data);
      const conDati = voci.find((v) => v.strumento && !STRUMENTI_SENZA_DATI.has(v.strumento));
      if (conDati) { t.conDati = true; attesa(t, conDati.strumento); prepara(t); }
    });
    t.fonte.addEventListener('fine', (e) => {
      t.fonte.close();
      if (turno !== t) return;
      const dati = JSON.parse(e.data);
      if (dati.stato === 'errore') { turno = null; notaSottotitoli('Non sono riuscita a rispondere: riprova o apri la chat.'); imposta('fermo'); return; }
      if (typeof dati.testo === 'string') {
        if (!t.conDati && !t.numero) { t.testo = dati.testo; t.letto = 0; t.coda = []; }   // non ancora letto nulla: si parte dal testo finale
        else riallinea(t, dati.testo);
      }
      t.conDati = true;
      mostraVerifica(dati.verifica);
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
    sorgente.connect(analizzatore);              // analizzatore → volume → altoparlante (audio())
    p.sorgente = sorgente;
    p.partito = audio().currentTime;
    if (!p.frase) aggiungiSottotitolo(p.testo, p.partito, buffer.duration);
    sorgente.onended = () => {
      if (turno !== t || t.suona !== p) return;
      if (!p.frase) { t.parlatoS += buffer.duration; t.sentito = (t.sentito || '') + p.testo; }
      p.finito = true;
      t.suona = null;
      if (t.parlatoS >= PARLATO_MAX_S && (t.coda.length || !t.finito)) {
        t.tagliato = true; t.coda = [];
        notaSottotitoli('La risposta continua nella chat: tocca «Apri nella chat» per leggerla tutta.');
      }
      suonaProssimo(t);
    };
    sorgente.start();
  }

  function finePossibile(t) {
    if (turno !== t || t.suona || t.coda.length || !(t.finito || t.tagliato)) return;
    turno = null;
    if (ASCOLTO_DOPO_MS > 0 && !daTastiera) ascolta(ASCOLTO_DOPO_MS);
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

  // ---------- frasi d'attesa: «Guardo il calendario.» mentre lo strumento lavora ----------
  // Una per risposta, la prima volta che parte uno strumento che legge dati e solo se Ada non sta già parlando.
  // L'audio si scarica al primo tocco (il server lo tiene in cache): così parte subito.
  let frasiPerStrumento = {};
  try { frasiPerStrumento = JSON.parse(document.getElementById('pa-frasi').textContent); } catch (e) { /* senza frasi */ }
  const audioFrasi = {};
  function urlFrase(chiave) { return cfg.frase.replace('/attimo/', `/${chiave}/`); }
  function preparaFrasi() {
    if (Object.keys(audioFrasi).length) return;
    new Set(Object.values(frasiPerStrumento)).forEach((chiave) => {
      audioFrasi[chiave] = fetch(urlFrase(chiave)).then((r) => (r.ok ? r.arrayBuffer() : null))
        .then((b) => (b ? audio().decodeAudioData(b) : null)).catch(() => null);
    });
  }
  function attesa(t, strumento) {
    const chiave = frasiPerStrumento[strumento];
    if (t.attesa || !chiave || !audioFrasi[chiave] || t.suona || t.numero) return;
    t.attesa = true;
    stato_el.textContent = { calendario: 'Guardo il calendario…', dati: 'Controllo nei dati…', documenti: 'Cerco nei documenti…',
                             comunicazioni: 'Guardo le comunicazioni…' }[chiave] || 'Un attimo…';
    t.coda.unshift({ frase: true, testo: '', audio: audioFrasi[chiave] });
    if (!t.suona) suonaProssimo(t);
  }

  // ---------- verifica: da dove vengono i dati della risposta ----------
  const STRUMENTI_SENZA_DATI = new Set(['data_e_ora', 'app_disponibili', 'elenco_viste', 'descrivi_vista', 'riassunto', 'verifica']);
  const verifica_el = radice.querySelector('[data-pa-fonti]');
  function mostraVerifica(v) {
    if (!verifica_el) return;
    verifica_el.className = 'pa-fonti';
    if (!v || !v.esito || v.esito === 'conversazione') { verifica_el.hidden = true; verifica_el.textContent = ''; return; }
    if (v.esito === 'senza fonti') {
      verifica_el.textContent = 'Non verificata: nessun dato letto dal gestionale';
      verifica_el.classList.add('is-avviso');
    } else if (v.esito === 'parziale') {
      verifica_el.textContent = 'Da controllare: ' + (v.non_verificati || []).slice(0, 3).join(', ') + (v.fonti.length ? ' · Fonti: ' + v.fonti.join(', ') : '');
      verifica_el.classList.add('is-avviso');
    } else {
      verifica_el.textContent = 'Verificata · ' + (v.fonti.length ? v.fonti.join(', ') : 'dati del gestionale');
    }
    verifica_el.hidden = false;
  }

  // ---------- sottotitoli ----------
  // Ogni pezzo letto entra come parole nascoste; il disegno le scopre man mano, in proporzione al tempo dell'audio.
  const righe = [];
  function svuotaSottotitoli() { righe.length = 0; risposta_el.textContent = ''; }
  function notaSottotitoli(testo) {
    const nota = document.createElement('span');
    nota.className = 'pa-nota';
    nota.textContent = testo;
    risposta_el.append(document.createElement('br'), nota);
  }
  function aggiungiSottotitolo(testo, inizio, durata) {
    const parole = testoVisibile(testo).split(' ').filter(Boolean);
    const blocco = document.createElement('span');
    const spans = parole.map((parola) => {
      const el = document.createElement('span');
      el.className = 'pa-parola';
      el.textContent = parola + ' ';
      blocco.append(el);
      return el;
    });
    risposta_el.append(blocco);
    righe.push({ spans, inizio, durata: Math.max(durata, 0.3) });
    while (risposta_el.childElementCount > 6) risposta_el.firstElementChild.remove();
  }
  function scopriParole() {
    if (!contesto || !righe.length) return;
    const ora = contesto.currentTime;
    for (const riga of righe) {
      const quante = Math.ceil(riga.spans.length * Math.min(1, (ora - riga.inizio) / riga.durata));
      for (let k = 0; k < quante; k += 1) riga.spans[k].classList.add('is-detta');
    }
    while (righe.length && righe[0].spans.every((el) => el.classList.contains('is-detta'))) righe.shift();
  }

  // ---------- scrivi invece di parlare ----------
  tastiera.addEventListener('click', () => {
    const apri = scrivi.hidden;
    scrivi.hidden = !apri;
    tastiera.setAttribute('aria-pressed', String(apri));
    if (apri) {
      if (stato === 'ascolto') { smettiDiAscoltare(true); imposta('fermo'); }
      scrivi.querySelector('input').focus();
    }
  });
  scrivi.addEventListener('submit', (e) => {
    e.preventDefault();
    const campo = scrivi.querySelector('input');
    const testo = campo.value.trim();
    if (!testo || stato === 'trascrivo') return;
    audio();
    preparaFrasi();
    smettiDiAscoltare(true);
    interrompi();
    campo.value = '';
    daTastiera = true;
    mostra(detto_el, testo);
    svuotaSottotitoli();
    chiedi(testo);
  });

  // ---------- in alto: app e notifiche ----------
  const apriApp = radice.querySelector('[data-pa-app-apri]');
  const menuApp = radice.querySelector('[data-pa-app-menu]');
  if (apriApp && menuApp) {
    const chiudiMenu = () => { menuApp.hidden = true; apriApp.setAttribute('aria-expanded', 'false'); };
    apriApp.addEventListener('click', (e) => {
      e.stopPropagation();
      menuApp.hidden = !menuApp.hidden;
      apriApp.setAttribute('aria-expanded', String(!menuApp.hidden));
    });
    document.addEventListener('click', (e) => { if (!menuApp.contains(e.target)) chiudiMenu(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') chiudiMenu(); });
  }
  const tastoMuto = radice.querySelector('[data-pa-muto]');
  function mostraMuto() {
    if (!tastoMuto) return;
    tastoMuto.setAttribute('aria-pressed', String(muto));
    const testo = muto ? 'Voce di Ada spenta: risponde solo per iscritto. Tocca per riaccenderla' : 'Spegni la voce di Ada: risponde solo per iscritto';
    tastoMuto.setAttribute('aria-label', testo);
    tastoMuto.title = muto ? 'Riaccendi la voce' : 'Senza voce';
  }
  if (tastoMuto) tastoMuto.addEventListener('click', () => {
    muto = !muto;
    try { localStorage.setItem('ai-parla-muto', muto ? '1' : '0'); } catch (e) { /* vale per questa pagina */ }
    if (volume) volume.gain.setTargetAtTime(muto ? 0 : 1, contesto.currentTime, 0.03);   // subito, anche a metà frase
    mostraMuto();
  });
  mostraMuto();
  const campanella = radice.querySelector('[data-pa-notifiche]');
  if (campanella) campanella.addEventListener('click', () => {      // «che notifiche ho?», come se l'avessi detto
    const testo = campanella.dataset.domanda;
    if (!testo || stato === 'trascrivo') return;
    audio();
    preparaFrasi();
    smettiDiAscoltare(true);
    interrompi();
    daTastiera = false;
    mostra(detto_el, testo);
    svuotaSottotitoli();
    const badge = campanella.querySelector('[data-pa-badge]');
    if (badge) badge.remove();
    chiedi(testo);
  });

  // ---------- tocchi ----------
  tocco.addEventListener('click', () => {
    audio();
    preparaFrasi();
    daTastiera = false;
    if (stato === 'fermo') { svuotaSottotitoli(); ascolta(SENZA_VOCE_MS); }
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

  // ---------- cubo e galassia ----------
  // Cielo a tutto schermo, come nella v2: stelle lontane che brillano e scorrono piano; una galassia di stelle che gira
  // attorno al cubo su un piano inclinato (quelle davanti passano sopra il cubo, quelle dietro sotto, come attorno a un
  // pianeta); una luna in orbita che mentre Ada pensa accelera e lascia la scia; onde quando la voce sale; ogni tanto
  // una stella cadente. Al centro il cubo del logo, in 3D e nei colori del tema: da fermo respira e oscilla attorno
  // alla posa del logo, ascoltando cresce con la voce, pensando gira su se stesso e luccica, parlando pulsa.
  // Colori dalle variabili CSS --pa-cubo-1..3 (sfumati qui). Con «riduci movimento» resta un cielo fermo.
  const cielo = radice.querySelector('.pa-cielo');
  const ctx = cielo && cielo.getContext && cielo.getContext('2d');
  const piano = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const colori = { cubo1: [127, 211, 216], cubo2: [43, 158, 166], cubo3: [27, 127, 134] };
  const onde = [], scia = [];
  const lontane = Array.from({ length: 120 }, () => ({
    x: Math.random(), y: Math.random(), z: 0.25 + Math.random() * 0.75, f: Math.random() * 6.28, v: 0.0006 + Math.random() * 0.0022,
  }));
  const galassia = Array.from({ length: piano ? 0 : 110 }, () => {
    const r = 1.45 + Math.pow(Math.random(), 0.8) * 2.1;                 // in raggi del cubo
    const braccio = Math.random() < 0.5 ? 0 : Math.PI;                    // due bracci a spirale
    return { a: braccio + r * 1.25 + (Math.random() - 0.5) * 0.9, r, z: 0.35 + Math.random() * 0.65 };
  });
  const INCLINAZIONE = -0.2;                                              // il piano della galassia, ruotato sullo schermo
  const SCHIACCIATA = 0.3;                                                // e visto di sbieco
  const POSA = Math.PI / 4, PENDENZA = Math.atan(1 / Math.SQRT2);         // la posa isometrica del logo
  const VERTICI = [[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]];
  const FACCE = [                                                         // [vertici, normale]
    [[3, 2, 6, 7], [0, 1, 0]], [[0, 1, 5, 4], [0, -1, 0]], [[4, 5, 6, 7], [0, 0, 1]],
    [[1, 0, 3, 2], [0, 0, -1]], [[5, 1, 2, 6], [1, 0, 0]], [[0, 4, 7, 3], [-1, 0, 0]],
  ];
  let livelloLiscio = 0, ultimaOnda = 0, prima = 0, giro = POSA, velocitaGiro = 0, luna = -0.6, velocitaLuna = 0;
  let cadente = null, prossimaCadente = 4000;
  function rgb(testo) {
    const m = /^#?([0-9a-f]{6})$/i.exec((testo || '').trim());
    if (!m) return null;
    const n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function verso(chiave, variabile) {
    const obiettivo = rgb(getComputedStyle(radice).getPropertyValue(variabile)) || colori[chiave];
    colori[chiave] = colori[chiave].map((v, k) => v + (obiettivo[k] - v) * 0.08);
  }
  const css = (c, a) => `rgba(${c[0] | 0}, ${c[1] | 0}, ${c[2] | 0}, ${a})`;
  const chiaro = (c, f) => c.map((v) => v + (255 - v) * f);
  const misto = (a, b, f) => a.map((v, k) => v + (b[k] - v) * f);
  function livelloVoce() {
    if (stato === 'parlo' && analizzatore) {
      const d = new Float32Array(analizzatore.fftSize);
      analizzatore.getFloatTimeDomainData(d);
      let somma = 0;
      for (let k = 0; k < d.length; k += 1) somma += d[k] * d[k];
      return Math.min(1, Math.sqrt(somma / d.length) * 5);
    }
    return stato === 'ascolto' ? livello : 0;
  }
  // un punto del piano della galassia: posizione sullo schermo e se sta davanti (sopra il cubo) o dietro
  function sulPiano(cx, cy, raggio, angolo) {
    const x = Math.cos(angolo) * raggio, y = Math.sin(angolo) * raggio * SCHIACCIATA;
    const c = Math.cos(INCLINAZIONE), s = Math.sin(INCLINAZIONE);
    return { x: cx + x * c - y * s, y: cy + x * s + y * c, davanti: Math.sin(angolo) > 0 };
  }
  function stella(x, y, r, colore, a) {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = css(colore, a);
    ctx.fill();
  }
  function disegnaGalassia(cx, cy, R, liv, pensa, davanti) {
    const colore = chiaro(colori.cubo1, 0.6);
    galassia.forEach((s) => {
      const p = sulPiano(cx, cy, R * (s.r + (stato === 'ascolto' ? liv * 0.35 : 0)), s.a);
      if (p.davanti !== davanti) return;
      const vicino = davanti ? 1.25 : 0.8;                                 // davanti più grandi e luminose
      stella(p.x, p.y, 1.2 * s.z * vicino, colore, Math.min(1, (0.22 + 0.4 * s.z * (0.55 + liv + (pensa ? 0.35 : 0))) * vicino));
    });
  }
  function disegnaLuna(cx, cy, R, liv, davanti) {
    const colore = chiaro(colori.cubo1, 0.15);
    scia.forEach((q, k) => {
      if (q.davanti !== davanti) return;
      stella(q.x, q.y, R * 0.08 * (k + 1) / scia.length, colore, 0.3 * (k + 1) / scia.length);
    });
    const p = sulPiano(cx, cy, R * 1.7, luna);
    if (p.davanti !== davanti) return;
    const r = R * 0.085 * (davanti ? 1.1 : 0.85) * (1 + liv * 0.25);
    const g = ctx.createRadialGradient(p.x - r * 0.35, p.y - r * 0.35, 1, p.x, p.y, r * 1.2);
    g.addColorStop(0, css(chiaro(colori.cubo1, 0.6), 1));
    g.addColorStop(1, css(colori.cubo2, 1));
    ctx.save();
    ctx.shadowColor = css(colori.cubo1, 0.9);
    ctx.shadowBlur = R * 0.25 + liv * 20;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fillStyle = g;
    ctx.fill();
    ctx.restore();
  }
  function disegnaCubo(cx, cy, R, liv, pensa, ora, beccheggio) {
    const s = R / 1.633;                                                  // semilato: nella posa del logo l'esagono ha raggio R
    const cg = Math.cos(giro), sg = Math.sin(giro), cp = Math.cos(PENDENZA + beccheggio), sp = Math.sin(PENDENZA + beccheggio);
    const ruota = ([x, y, z]) => {
      const x1 = x * cg + z * sg, z1 = -x * sg + z * cg;
      return [x1, y * cp - z1 * sp, y * sp + z1 * cp];
    };
    const punti = VERTICI.map((v) => { const [x, y] = ruota(v); return [cx + x * s, cy - y * s]; });
    const luccichio = pensa && !piano ? 0.1 + 0.12 * Math.sin(ora / 160) : 0;
    const visibili = FACCE.map(([idx, n]) => ({ idx, n: ruota(n) })).filter((f) => f.n[2] > 0.001)
      .sort((a, b) => a.n[1] - b.n[1]);                                   // la faccia in alto per ultima
    ctx.save();
    ctx.lineJoin = 'round';
    ctx.lineWidth = R * 0.14;                                             // il bordo dello stesso colore arrotonda gli spigoli
    visibili.forEach((f, k) => {
      // in alto il colore chiaro; sui fianchi dal medio (a sinistra) allo scuro (a destra), sfumato mentre gira
      const fianco = misto(colori.cubo3, colori.cubo2, (1 - f.n[0]) / 2);
      const colore = chiaro(misto(fianco, colori.cubo1, Math.max(0, f.n[1])), luccichio * (f.n[1] > 0.5 ? 0.6 : 1));
      ctx.beginPath();
      f.idx.forEach((i, j) => (j ? ctx.lineTo(punti[i][0], punti[i][1]) : ctx.moveTo(punti[i][0], punti[i][1])));
      ctx.closePath();
      ctx.fillStyle = ctx.strokeStyle = css(colore, 1);
      if (k === 0) { ctx.shadowColor = css(colori.cubo2, 0.8); ctx.shadowBlur = R * 0.35 + liv * 34 + (pensa ? 12 : 0); }
      ctx.fill(); ctx.stroke();
      ctx.shadowBlur = 0;
    });
    // spigoli in luce tra le facce visibili, come nel logo
    ctx.beginPath();
    for (let a = 0; a < visibili.length; a += 1) {
      for (let b = a + 1; b < visibili.length; b += 1) {
        const comuni = visibili[a].idx.filter((i) => visibili[b].idx.includes(i));
        if (comuni.length !== 2) continue;
        const [p, q] = comuni.map((i) => punti[i]);
        const mx = (p[0] + q[0]) / 2, my = (p[1] + q[1]) / 2;
        ctx.moveTo(mx + (p[0] - mx) * 0.86, my + (p[1] - my) * 0.86);    // un po' più corti: non toccano il bordo
        ctx.lineTo(mx + (q[0] - mx) * 0.86, my + (q[1] - my) * 0.86);
      }
    }
    ctx.strokeStyle = `rgba(255, 255, 255, ${0.3 + liv * 0.3 + luccichio})`;
    ctx.lineWidth = Math.max(1, R * 0.045);
    ctx.lineCap = 'round';
    ctx.stroke();
    ctx.restore();
  }
  function disegna(ora) {
    requestAnimationFrame(disegna);
    scopriParole();
    if (!ctx) return;
    const dt = prima ? Math.min(50, ora - prima) : 16;
    prima = ora;
    verso('cubo1', '--pa-cubo-1'); verso('cubo2', '--pa-cubo-2'); verso('cubo3', '--pa-cubo-3');
    const larga = cielo.clientWidth, alta = cielo.clientHeight, dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (!larga || !alta) return;
    if (cielo.width !== Math.round(larga * dpr) || cielo.height !== Math.round(alta * dpr)) {
      cielo.width = Math.round(larga * dpr); cielo.height = Math.round(alta * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, larga, alta);
    livelloLiscio += (livelloVoce() - livelloLiscio) * 0.22;
    const liv = piano ? 0 : livelloLiscio;
    tocco.style.setProperty('--pa-livello', liv.toFixed(3));
    const t = piano ? 0 : ora;
    const pensa = stato === 'penso' || stato === 'trascrivo';

    // il cubo sta al centro dello spazio libero (.pa-sfera), il cielo copre tutta la pagina
    const box = tela.getBoundingClientRect(), base = cielo.getBoundingClientRect();
    const lato = Math.min(box.width, box.height);
    const respiro = stato === 'fermo' ? Math.sin(t / 1500) * 0.035 : 0;
    const R = Math.max(14, lato * 0.21) * (1 + respiro + (stato === 'parlo' ? liv * 0.12 : stato === 'ascolto' ? liv * 0.07 : 0));
    const cx = box.left - base.left + box.width / 2;
    const cy = box.top - base.top + box.height / 2 + Math.sin(t / 1900) * R * 0.05;

    // stelle lontane: brillano e scorrono piano, più vive con la voce
    const lontana = chiaro(colori.cubo1, 0.75);
    lontane.forEach((s) => {
      const x = ((s.x + t * 0.0000035 * s.z) % 1) * larga, y = s.y * alta;
      const brilla = piano ? 0.6 : 0.5 + 0.5 * Math.sin(s.f + t * s.v);
      stella(x, y, 0.5 + s.z * 0.9, lontana, (0.1 + 0.45 * s.z * brilla) * (1 + liv * 0.6));
    });

    // nebulosa e alone del colore del tema, più forti con la voce e mentre pensa
    const nebulosa = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 6);
    nebulosa.addColorStop(0, css(colori.cubo1, 0.07 + 0.03 * Math.sin(t / 2300)));
    nebulosa.addColorStop(1, css(colori.cubo1, 0));
    ctx.fillStyle = nebulosa;
    ctx.fillRect(0, 0, larga, alta);
    const forza = pensa ? 0.3 + 0.08 * Math.sin(t / 300) : 0.18 + liv * 0.38;
    const alone = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * (2.6 + liv * 0.9));
    alone.addColorStop(0, css(colori.cubo2, forza));
    alone.addColorStop(0.5, css(colori.cubo2, forza * 0.35));
    alone.addColorStop(1, css(colori.cubo2, 0));
    ctx.fillStyle = alone;
    ctx.fillRect(0, 0, larga, alta);

    // stella cadente, ogni tanto
    if (!piano) {
      prossimaCadente -= dt;
      if (!cadente && prossimaCadente <= 0) {
        cadente = { x: Math.random() * larga * 0.8, y: Math.random() * alta * 0.35, inizio: ora };
        prossimaCadente = 5000 + Math.random() * 7000;
      }
      if (cadente) {
        const p = (ora - cadente.inizio) / 900;
        if (p >= 1) cadente = null;
        else {
          const x = cadente.x + p * larga * 0.35, y = cadente.y + p * alta * 0.12;
          const coda = ctx.createLinearGradient(x, y, x - larga * 0.12, y - alta * 0.04);
          coda.addColorStop(0, css(lontana, 0.8 * (1 - p)));
          coda.addColorStop(1, css(lontana, 0));
          ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - larga * 0.12, y - alta * 0.04);
          ctx.strokeStyle = coda; ctx.lineWidth = 1.6; ctx.lineCap = 'round'; ctx.stroke();
        }
      }
    }

    // onde che si allargano quando la voce sale (ascolto e parola)
    if ((stato === 'parlo' || stato === 'ascolto') && !piano && liv > 0.35 && ora - ultimaOnda > 260) { onde.push(ora); ultimaOnda = ora; }
    for (let k = onde.length - 1; k >= 0; k -= 1) {
      const p = (ora - onde[k]) / 1600;
      if (p >= 1) { onde.splice(k, 1); continue; }
      ctx.beginPath();
      ctx.arc(cx, cy, R * (1.1 + p * 1.6), 0, Math.PI * 2);
      ctx.strokeStyle = css(chiaro(colori.cubo1, 0.3), (1 - p) * 0.4);
      ctx.lineWidth = 2.2 * (1 - p) + 0.5;
      ctx.stroke();
    }

    // la galassia gira: le stelle vicine più veloci (come in un vortice), tutte molto più veloci mentre pensa
    if (!piano) galassia.forEach((s) => { s.a += (0.00042 / s.r) * (pensa ? 5 : 1) * dt; });
    velocitaLuna += ((pensa ? 0.0034 : 0.00045) - velocitaLuna) * 0.04;
    if (!piano) luna += velocitaLuna * dt;
    scia.push(sulPiano(cx, cy, R * 1.7, luna));
    while (scia.length > (pensa && !piano ? 26 : 8)) scia.shift();

    // il cubo: oscilla attorno alla posa del logo; pensando gira e poi torna alla posa
    velocitaGiro += ((pensa && !piano ? 0.0026 : 0) - velocitaGiro) * 0.05;
    if (velocitaGiro > 0.0003) giro += velocitaGiro * dt;
    else {
      const posa = POSA + Math.round((giro - POSA) / (Math.PI / 2)) * (Math.PI / 2) + (piano ? 0 : Math.sin(t / 2600) * 0.16);
      giro += (posa - giro) * 0.06;
    }
    const beccheggio = piano ? 0 : Math.sin(t / 3100) * 0.05;

    disegnaGalassia(cx, cy, R, liv, pensa, false);                        // dietro il cubo
    disegnaLuna(cx, cy, R, liv, false);
    disegnaCubo(cx, cy, R, liv, pensa, ora, beccheggio);
    disegnaGalassia(cx, cy, R, liv, pensa, true);                         // davanti
    disegnaLuna(cx, cy, R, liv, true);
  }
  requestAnimationFrame(disegna);
  imposta('fermo');
})();
