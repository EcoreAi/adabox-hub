// La chiamata: anteprima e ingresso, collegamenti tra browser (WebRTC), controlli, ospiti.
(function () {
  const r = document.getElementById('cm');
  const $ = (id) => document.getElementById(id);
  const d = r.dataset;
  const collega = d.collega === '1';
  const sicuro = window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia;
  let flussoLocale = null, audioOn = true, camOn = d.video === '1', io = null, segreto = null, ice = [], fonte = null;
  let tracciaVideo = null, schermo = null, mano = false, ptt = false, spazio = false, sfoca = null;
  const pari = new Map();                       // id -> {pc, cortese, offrendo, ignora, nome, riquadro, stato, video}

  // --- anteprima ---
  function errore(t) { $('cm-errore').textContent = t; $('cm-errore').hidden = !t; }
  function aggiornaProva() {
    $('cm-prova-mic').setAttribute('aria-pressed', audioOn); $('cm-prova-cam').setAttribute('aria-pressed', camOn);
    const ha = flussoLocale && flussoLocale.getVideoTracks().length && camOn;
    $('cm-prova').style.visibility = ha ? 'visible' : 'hidden'; $('cm-prova-vuota').hidden = !!ha;
  }
  async function apriDispositivi(mic, cam) {
    if (!sicuro) { flussoLocale = new MediaStream(); audioOn = false; camOn = false; $('cm-insicuro').hidden = false; aggiornaProva(); return; }
    if (flussoLocale) flussoLocale.getTracks().forEach((t) => t.stop());
    const voglio = async (vincoli) => { try { return await navigator.mediaDevices.getUserMedia(vincoli); } catch (e) { return null; } };
    const a = { audio: mic ? { deviceId: { exact: mic } } : true };
    const v = { video: cam ? { deviceId: { exact: cam } } : { width: { ideal: 1280 }, height: { ideal: 720 } } };
    flussoLocale = (await voglio({ ...a, ...v })) || (await voglio(a)) || (await voglio(v)) || new MediaStream();
    if (!flussoLocale.getAudioTracks().length) { audioOn = false; $('cm-prova-mic').disabled = true; }
    if (!flussoLocale.getVideoTracks().length) { camOn = false; $('cm-prova-cam').disabled = true; }
    $('cm-prova').srcObject = flussoLocale;
    applicaLocali(); aggiornaProva();
    const elenco = await navigator.mediaDevices.enumerateDevices();
    riempi('cm-mic', 'cm-scelta-mic', elenco.filter((x) => x.kind === 'audioinput'), flussoLocale.getAudioTracks()[0]);
    riempi('cm-cam', 'cm-scelta-cam', elenco.filter((x) => x.kind === 'videoinput'), flussoLocale.getVideoTracks()[0]);
  }
  function riempi(id, riga, voci, traccia) {
    const s = $(id); s.textContent = '';
    voci.forEach((v, i) => { const o = document.createElement('option'); o.value = v.deviceId; o.textContent = v.label || `Dispositivo ${i + 1}`; s.appendChild(o); });
    if (traccia) s.value = traccia.getSettings().deviceId || s.value;
    $(riga).hidden = voci.length < 2;
  }
  function applicaLocali() {
    if (!flussoLocale) return;
    flussoLocale.getAudioTracks().forEach((t) => { t.enabled = audioOn && (!ptt || spazio); });
    flussoLocale.getVideoTracks().forEach((t) => { t.enabled = camOn; });
  }
  $('cm-prova-mic').addEventListener('click', () => { audioOn = !audioOn; applicaLocali(); aggiornaProva(); });
  $('cm-prova-cam').addEventListener('click', () => { camOn = !camOn; applicaLocali(); aggiornaProva(); });
  $('cm-mic').addEventListener('change', (e) => apriDispositivi(e.target.value, $('cm-cam').value));
  $('cm-cam').addEventListener('change', (e) => apriDispositivi($('cm-mic').value, e.target.value));
  apriDispositivi();

  // --- rete ---
  const manda = (url, corpo) => fetch(url, { method: 'POST', headers: { 'X-Segreto': segreto, 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) }).catch(() => {});
  const segnale = (a, tipo, corpo) => manda(d.segnale, { a, tipo, corpo });
  const dichiara = () => manda(d.stato, { microfono: audioOn, camera: camOn, schermo: !!schermo, mano });
  const conCsrf = (url, dati) => fetch(url, { method: 'POST', headers: { 'X-CSRFToken': d.csrf }, body: new URLSearchParams(dati) });

  $('cm-entra').addEventListener('click', async () => {
    errore('');
    const nome = $('cm-nome') ? $('cm-nome').value.trim() : '';
    if ($('cm-nome') && !nome) { errore('Scrivi il tuo nome.'); $('cm-nome').focus(); return; }
    $('cm-entra').disabled = true;
    try {
      const risposta = await conCsrf(d.entra, { nome, microfono: audioOn ? '1' : '0', camera: camOn ? '1' : '0' });
      const dati = await risposta.json();
      if (!risposta.ok) { errore(dati.errore || 'Non è stato possibile entrare.'); $('cm-entra').disabled = false; return; }
      io = dati.io; segreto = dati.segreto; ice = dati.ice; window.dsNome = dati.nome;
      ascolta(dati.dopo);
      if (dati.ammesso) { entraInStanza(dati.altri); (dati.attesa || []).forEach((g) => bussa(g.id, g.nome)); } else { $('cm-ingresso').hidden = true; $('cm-attesa').hidden = false; }
    } catch (e) { errore('Connessione assente: riprova.'); $('cm-entra').disabled = false; }
  });
  function ascolta(dopo) {
    fonte = new EventSource(`${d.eventi}?s=${encodeURIComponent(segreto)}&dopo=${dopo}`);
    fonte.addEventListener('segnale', (e) => { suSegnale(JSON.parse(e.data)); });
    fonte.addEventListener('fuori', () => termina('Sei uscito dalla chiamata'));
  }
  function termina(titolo) {
    if (fonte) fonte.close();
    pari.forEach((p) => p.pc.close()); pari.clear();
    if (flussoLocale) flussoLocale.getTracks().forEach((t) => t.stop());
    if (schermo) schermo.getTracks().forEach((t) => t.stop());
    if (sfoca) sfoca.ferma();
    segreto = null;
    ['cm-ingresso', 'cm-attesa', 'cm-stanza'].forEach((i) => { $(i).hidden = true; });
    $('cm-fine-titolo').textContent = titolo; $('cm-fine').hidden = false;
  }
  window.addEventListener('pagehide', () => { if (segreto) navigator.sendBeacon(d.esci, segreto); });

  function entraInStanza(altri) {
    $('cm-prova').srcObject = null;
    $('cm-ingresso').hidden = true; $('cm-attesa').hidden = true; $('cm-stanza').hidden = false;
    aggiungiMio();
    if (!sicuro || !flussoLocale.getAudioTracks().length) $('cm-mic-tasto').disabled = true;
    if (!sicuro || !flussoLocale.getVideoTracks().length) { $('cm-cam-tasto').disabled = true; $('cm-sfoca-tasto').disabled = true; }
    if (!sicuro || !navigator.mediaDevices.getDisplayMedia) $('cm-schermo-tasto').disabled = true;
    if (!sicuro) $('cm-ptt-tasto').disabled = true;
    aggiornaTasti();
    // chi arriva dopo si presenta: fa lui l'offerta a chi c'è già
    altri.forEach((a) => { const p = creaPari(a, true); p.stato = a; aggiornaRiquadro(p); });
    elencoPersone();
  }

  function suSegnale(s) {
    switch (s.tipo) {
      case 'ammesso': entraInStanza(s.altri || []); break;
      case 'rifiutato': termina('Non ti hanno fatto entrare'); break;
      case 'bussa': bussa(s.id, s.nome); break;
      case 'attesa_chiusa': togliRichiesta(s.id); break;
      case 'entrato': { const p = creaPari(s, false); p.stato = s; aggiornaRiquadro(p); elencoPersone(); break; }
      case 'uscito': togliPari(s.id); break;
      case 'stato': { const p = pari.get(s.id); if (p) { p.stato = s; aggiornaRiquadro(p); elencoPersone(); } break; }
      case 'offerta': case 'risposta': suDescrizione(s); break;
      case 'candidato': suCandidato(s); break;
      case 'fine': termina('La chiamata è terminata'); break;
      default: break;
    }
  }

  // --- collegamenti ---
  // Un solo lato apre il collegamento, chi arriva dopo: due offerte incrociate non si scontrano mai. Chi riceve l'offerta
  // usa le linee audio e video che gli vengono proposte, e da lì in poi i media si scambiano senza rinegoziare.
  function creaPari(info, offro) {
    if (pari.has(info.id)) return pari.get(info.id);
    const pc = new RTCPeerConnection({ iceServers: ice });
    const p = { id: info.id, pc, cortese: io > info.id, offrendo: false, ignora: false, risposta: false, stato: info,
                flusso: new MediaStream(), inAttesa: [], coda: Promise.resolve(), pronto: false };
    pari.set(info.id, p);
    pc.ontrack = (e) => { p.flusso.addTrack(e.track); if (p.video) p.video.srcObject = p.flusso; osservaVoce(p); };
    pc.onicecandidate = (e) => { if (e.candidate) segnale(p.id, 'candidato', e.candidate); };
    pc.onnegotiationneeded = () => { if (p.pronto) iniziaOfferta(p); };   // dopo il primo giro: riavvii della rete
    pc.onconnectionstatechange = () => aggiornaRiquadro(p);
    pc.oniceconnectionstatechange = () => {
      if (pc.iceConnectionState === 'failed' && !p.cortese) { try { pc.restartIce(); } catch (e) { /* si riproverà */ } }
    };
    costruisciRiquadro(p);
    if (offro) {
      p.mittenteAudio = pc.addTransceiver('audio', { direction: 'sendrecv' }).sender;
      p.mittenteVideo = pc.addTransceiver('video', { direction: 'sendrecv' }).sender;
      collegaTracce(p);
      iniziaOfferta(p).then(() => { p.pronto = true; });
    }
    return p;
  }
  function collegaTracce(p) {
    const audio = flussoLocale && flussoLocale.getAudioTracks()[0];
    if (p.mittenteAudio && audio) p.mittenteAudio.replaceTrack(audio);
    const video = tracciaInUscita();
    if (p.mittenteVideo && video) p.mittenteVideo.replaceTrack(video);
  }
  async function iniziaOfferta(p) {
    if (p.offrendo) return;
    try {
      p.offrendo = true;
      await p.pc.setLocalDescription();
      segnale(p.id, 'offerta', p.pc.localDescription);
    } catch (e) { /* ritenterà alla prossima negoziazione */ } finally { p.offrendo = false; }
  }
  // i segnali di una stessa persona si trattano uno alla volta, nell'ordine in cui arrivano
  function inCoda(p, lavoro) { p.coda = p.coda.then(lavoro).catch((e) => console.warn('segnale', e)); return p.coda; }
  function suDescrizione(s) {
    const p = pari.get(s.id) || creaPari({ id: s.id, nome: '…' }, false);
    return inCoda(p, async () => {
      const descr = s.corpo;
      const libero = !p.offrendo && (p.pc.signalingState === 'stable' || p.risposta);
      const scontro = descr.type === 'offer' && !libero;
      p.ignora = !p.cortese && scontro;
      if (p.ignora) return;
      p.risposta = descr.type === 'answer';
      await p.pc.setRemoteDescription(descr);
      p.risposta = false;
      if (descr.type === 'offer') {
        p.pc.getTransceivers().forEach((t) => {
          const tipo = t.receiver.track.kind;
          t.direction = 'sendrecv';
          if (tipo === 'audio' && !p.mittenteAudio) p.mittenteAudio = t.sender;
          if (tipo === 'video' && !p.mittenteVideo) p.mittenteVideo = t.sender;
        });
        collegaTracce(p);
        await p.pc.setLocalDescription();
        segnale(p.id, 'risposta', p.pc.localDescription);
        p.pronto = true;
      }
      for (const c of p.inAttesa.splice(0)) { try { await p.pc.addIceCandidate(c); } catch (e) { /* candidato scaduto */ } }
    });
  }
  function suCandidato(s) {
    const p = pari.get(s.id);
    if (!p) return null;
    return inCoda(p, async () => {
      if (p.ignora) return;
      if (!p.pc.remoteDescription) { p.inAttesa.push(s.corpo); return; }
      try { await p.pc.addIceCandidate(s.corpo); } catch (e) { if (!p.ignora) console.warn('candidato', e); }
    });
  }
  function togliPari(id) {
    const p = pari.get(id);
    if (!p) return;
    p.pc.close(); if (p.riquadro) p.riquadro.remove(); pari.delete(id); layout(); elencoPersone();
  }

  // --- riquadri ---
  function riquadro(nome, mio) {
    const el = document.createElement('div');
    el.className = 'cm-riquadro senza-video' + (mio ? ' is-mio' : '');
    const v = document.createElement('video'); v.autoplay = true; v.playsInline = true; if (mio) v.muted = true;
    const ini = document.createElement('div'); ini.className = 'cm-iniziale'; const s = document.createElement('span'); s.textContent = (nome || '?').slice(0, 1).toUpperCase(); ini.appendChild(s);
    const et = document.createElement('div'); et.className = 'cm-etichetta'; const n = document.createElement('span'); n.textContent = nome; const m = document.createElement('span'); m.className = 'cm-muto'; et.append(n, m);
    const h = document.createElement('div'); h.className = 'cm-mano'; h.textContent = '✋'; h.hidden = true;
    const rete = document.createElement('div'); rete.className = 'cm-stato-rete'; rete.hidden = true;
    el.append(v, ini, et, h, rete);
    $('cm-griglia').appendChild(el);
    return { el, v, m, h, rete, n };
  }
  let mio = null;
  function aggiungiMio() {
    mio = riquadro(`${window.dsNome || 'Tu'} (tu)`, true);
    aggiornaMio(); osservaLocale();
  }
  function aggiornaMio() {
    if (!mio) return;
    const flusso = schermo || (sfoca ? sfoca.uscita : flussoLocale);
    if (mio.v.srcObject !== flusso) mio.v.srcObject = flusso;
    mio.el.classList.toggle('senza-video', !schermo && !camOn);
    mio.el.classList.toggle('is-schermo', !!schermo);
    mio.m.textContent = audioOn ? '' : '🔇'; mio.h.hidden = !mano;
    layout();
  }
  function costruisciRiquadro(p) { const c = riquadro(p.stato.nome, false); p.riquadro = c.el; p.video = c.v; p.c = c; c.v.srcObject = p.flusso; layout(); }
  function aggiornaRiquadro(p) {
    if (!p.c) return;
    const s = p.stato;
    p.c.n.textContent = s.nome + (s.ospite ? ' · ospite' : '');
    p.c.el.classList.toggle('senza-video', s.camera === false && !s.schermo);
    p.c.el.classList.toggle('is-schermo', !!s.schermo);
    p.c.m.textContent = s.microfono === false ? '🔇' : ''; p.c.h.hidden = !s.mano;
    const st = p.pc.connectionState;
    p.c.rete.hidden = st === 'connected' || st === 'new';
    p.c.rete.textContent = st === 'failed' ? 'Connessione non riuscita' : 'Collegamento…';
    p.c.el.dataset.rete = st;
    layout();
  }
  function layout() {
    const griglia = $('cm-griglia');
    griglia.classList.toggle('ha-schermo', !!griglia.querySelector('.cm-riquadro.is-schermo'));
    $('cm-n').textContent = pari.size + 1;
  }
  function elencoPersone() {
    const ul = $('cm-persone'); ul.textContent = '';
    const voce = (nome, nota) => { const li = document.createElement('li'); const a = document.createElement('span'); a.textContent = nome; const b = document.createElement('small'); b.textContent = nota; li.append(a, b); ul.appendChild(li); };
    voce(`${window.dsNome || 'Tu'} (tu)`, mano ? '✋' : '');
    pari.forEach((p) => voce(p.stato.nome, `${p.stato.ospite ? 'ospite ' : ''}${p.stato.mano ? '✋' : ''}`));
  }

  // chi sta parlando
  let audioCtx;
  function analizza(flusso, riq) {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
      const nodo = audioCtx.createAnalyser(); nodo.fftSize = 512;
      audioCtx.createMediaStreamSource(flusso).connect(nodo);
      const dati = new Uint8Array(nodo.frequencyBinCount);
      const t = setInterval(() => {
        if (!riq.isConnected) { clearInterval(t); return; }
        nodo.getByteFrequencyData(dati);
        riq.classList.toggle('parla', dati.reduce((a, b) => a + b, 0) / dati.length > 18);
      }, 250);
    } catch (e) { /* senza indicatore */ }
  }
  function osservaVoce(p) { if (!p.voce && p.flusso.getAudioTracks().length) { p.voce = true; analizza(p.flusso, p.riquadro); } }
  function osservaLocale() { if (flussoLocale && flussoLocale.getAudioTracks().length) analizza(new MediaStream(flussoLocale.getAudioTracks()), mio.el); }

  // --- controlli ---
  function tracciaInUscita() {
    if (schermo) return schermo.getVideoTracks()[0];
    if (sfoca) return sfoca.uscita.getVideoTracks()[0];
    return flussoLocale && flussoLocale.getVideoTracks()[0];
  }
  function inviaVideo() { const t = tracciaInUscita(); pari.forEach((p) => { if (p.mittenteVideo) p.mittenteVideo.replaceTrack(t || null); }); }
  function aggiornaTasti() {
    $('cm-mic-tasto').setAttribute('aria-pressed', audioOn); $('cm-cam-tasto').setAttribute('aria-pressed', camOn);
    $('cm-schermo-tasto').setAttribute('aria-pressed', !!schermo); $('cm-mano-tasto').setAttribute('aria-pressed', mano);
    $('cm-sfoca-tasto').setAttribute('aria-pressed', !!sfoca); $('cm-ptt-tasto').setAttribute('aria-pressed', ptt);
    $('cm-ptt-avviso').hidden = !ptt;
    applicaLocali(); aggiornaMio();
  }
  $('cm-mic-tasto').addEventListener('click', () => { audioOn = !audioOn; aggiornaTasti(); dichiara(); });
  $('cm-cam-tasto').addEventListener('click', () => { camOn = !camOn; aggiornaTasti(); dichiara(); });
  $('cm-mano-tasto').addEventListener('click', () => { mano = !mano; aggiornaTasti(); dichiara(); elencoPersone(); });
  $('cm-esci').addEventListener('click', () => { if (segreto) manda(d.esci, {}); termina('Sei uscito dalla chiamata'); });
  async function fermaSchermo() { if (!schermo) return; schermo.getTracks().forEach((t) => t.stop()); schermo = null; inviaVideo(); aggiornaTasti(); dichiara(); }
  $('cm-schermo-tasto').addEventListener('click', async () => {
    if (schermo) { fermaSchermo(); return; }
    try {
      schermo = await navigator.mediaDevices.getDisplayMedia({ video: true });
      schermo.getVideoTracks()[0].addEventListener('ended', fermaSchermo);
      inviaVideo(); aggiornaTasti(); dichiara();
    } catch (e) { schermo = null; }
  });
  $('cm-ptt-tasto').addEventListener('click', () => { ptt = !ptt; aggiornaTasti(); });
  const inCampo = (t) => t && t.matches && t.matches('input, select, textarea');
  document.addEventListener('keydown', (e) => { if (ptt && e.code === 'Space' && !inCampo(e.target) && !spazio) { e.preventDefault(); spazio = true; applicaLocali(); } });
  document.addEventListener('keyup', (e) => { if (ptt && e.code === 'Space') { spazio = false; applicaLocali(); } });
  window.addEventListener('blur', () => { if (spazio) { spazio = false; applicaLocali(); } });

  // sfocatura dello sfondo: il modello gira nel browser e si scarica solo la prima volta che serve
  function carica(src) { return new Promise((ok, no) => { const s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = no; document.head.appendChild(s); }); }
  async function creaSfocatura() {
    if (!window.SelfieSegmentation) await carica(`${d.selfie}selfie_segmentation.js`);
    const seg = new window.SelfieSegmentation({ locateFile: (f) => `${d.selfie}${f}` });
    seg.setOptions({ modelSelection: 1 });
    const sorgente = document.createElement('video'); sorgente.muted = true; sorgente.playsInline = true;
    sorgente.srcObject = new MediaStream(flussoLocale.getVideoTracks()); await sorgente.play();
    const tela = document.createElement('canvas');
    tela.width = sorgente.videoWidth || 640; tela.height = sorgente.videoHeight || 360;
    const ctx = tela.getContext('2d');
    seg.onResults((ris) => {
      ctx.save();
      ctx.clearRect(0, 0, tela.width, tela.height);
      ctx.drawImage(ris.segmentationMask, 0, 0, tela.width, tela.height);
      ctx.globalCompositeOperation = 'source-in';
      ctx.drawImage(ris.image, 0, 0, tela.width, tela.height);
      ctx.globalCompositeOperation = 'destination-over';
      ctx.filter = 'blur(14px)';
      ctx.drawImage(ris.image, 0, 0, tela.width, tela.height);
      ctx.restore();
    });
    await seg.initialize();
    let attivo = true;
    (async function giro() {
      while (attivo) {
        if (sorgente.readyState >= 2) { try { await seg.send({ image: sorgente }); } catch (e) { /* fotogramma saltato */ } }
        await new Promise((f) => setTimeout(f, 50));
      }
    }());
    return { uscita: tela.captureStream(20), ferma() { attivo = false; this.uscita.getTracks().forEach((t) => t.stop()); sorgente.srcObject = null; seg.close(); } };
  }
  $('cm-sfoca-tasto').addEventListener('click', async () => {
    const tasto = $('cm-sfoca-tasto');
    if (sfoca) { sfoca.ferma(); sfoca = null; inviaVideo(); aggiornaTasti(); return; }
    tasto.disabled = true; tasto.textContent = 'Preparo…';
    try { sfoca = await creaSfocatura(); window.dsSfocaPronta = true; inviaVideo(); } catch (e) { tasto.title = 'Questo browser non riesce a sfocare lo sfondo'; }
    tasto.disabled = false; tasto.textContent = 'Sfoca sfondo'; aggiornaTasti();
  });

  // --- persone e ospiti ---
  const lato = $('cm-lato');
  $('cm-persone-tasto').addEventListener('click', () => { lato.hidden = !lato.hidden; elencoPersone(); });
  $('cm-lato-chiudi').addEventListener('click', () => { lato.hidden = true; });
  const volante = $('cm-volante');
  function bussa(id, nome) {
    if (!collega || document.querySelector(`[data-richiesta="${id}"]`)) return;
    const costruisci = () => {
      const c = document.createElement('div'); c.className = 'cm-richiesta'; c.dataset.richiesta = id;
      const t = document.createElement('div'); t.textContent = `${nome} chiede di entrare`;
      const az = document.createElement('div'); az.className = 'cm-richiesta-azioni';
      const si = document.createElement('button'); si.type = 'button'; si.className = 'cm-tasto'; si.textContent = 'Fai entrare';
      const no = document.createElement('button'); no.type = 'button'; no.className = 'cm-tasto'; no.textContent = 'Rifiuta';
      si.addEventListener('click', () => conCsrf(d.ammetti, { id, si: '1' }));
      no.addEventListener('click', () => conCsrf(d.ammetti, { id, si: '0' }));
      az.append(si, no); c.append(t, az); return c;
    };
    $('cm-richieste').appendChild(costruisci());
    volante.appendChild(costruisci()); volante.hidden = false;
  }
  function togliRichiesta(id) {
    document.querySelectorAll(`[data-richiesta="${id}"]`).forEach((e) => e.remove());
    volante.hidden = !volante.children.length;
  }
  const ospiti = $('cm-ospiti');
  if (ospiti) {
    $('cm-link-riga').hidden = !ospiti.checked;
    ospiti.addEventListener('change', async () => {
      $('cm-link-riga').hidden = !ospiti.checked;
      await conCsrf(d.ospiti, { si: ospiti.checked ? '1' : '0' });
    });
    $('cm-copia').addEventListener('click', () => {
      const v = $('cm-link').value;
      (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(() => { $('cm-copia').textContent = 'Copiato'; }, () => { $('cm-link').select(); });
    });
  }
  window.dsChiamata = { pari, stato: () => ({ io, n: pari.size }) };
})();
