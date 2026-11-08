/* «Scrivi con Ada».
   - Campi di istruzioni (data-scrivi-con-ada="progetto|assistente|pianificata"): intervista o miglioramento.
   - Ogni altro campo di testo dei form delle viste e il composer del chatter (campo «libero»): un'istruzione rapida o
     scritta, poi la proposta, che entra nel campo solo con «Usa questo testo» (sostituisce) o «Aggiungi in fondo».
   - «Riassumi con Ada» nel dettaglio di un record: il riassunto, da copiare o salvare come nota.
   Niente si salva da solo: il campo si salva con il suo form, come sempre. */
(function () {
  const dialogo = document.getElementById('ai-scrivi');
  const script = document.currentScript || document.querySelector('script[src*="scrivi_con_ada.js"]');
  if (!dialogo || !script) return;
  const domandePer = JSON.parse(document.getElementById('ai-scrivi-campi').textContent);
  const csrf = () => (document.querySelector('input[name="csrfmiddlewaretoken"]') || {}).value
    || (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';
  const q = (sel) => dialogo.querySelector(sel);
  const errore = q('[data-scrivi-errore]');
  const titolo = q('#ai-scrivi-titolo');
  let stato = { campo: null, chiave: '', giro: 0, modo: 'campo', rapida: '' };

  const BOTTONI = {
    domande: ['scrivi'], scelta: ['migliora', 'domande'], istruzione: ['libero'], attesa: [],
    bozza: ['usa', 'domande'], bozza_libero: ['aggiungi', 'usa'], riassunto: ['copia', 'nota'],
  };
  const fase = (nome, bottoni) => {
    const sezione = nome.startsWith('bozza') || nome === 'riassunto' ? 'bozza' : nome;
    dialogo.querySelectorAll('[data-fase]').forEach((s) => { s.hidden = s.dataset.fase !== sezione; });
    const vedi = BOTTONI[bottoni || nome];
    dialogo.querySelectorAll('[data-azione]').forEach((b) => {
      b.hidden = !vedi.includes(b.dataset.azione) || (b.dataset.azione === 'nota' && !stato.nota);
    });
  };
  const sbaglio = (testo) => { errore.textContent = testo || ''; errore.hidden = !testo; };

  const mostraDomande = () => {
    const contenitore = q('[data-domande]');
    contenitore.replaceChildren(...(domandePer[stato.chiave] || { domande: [] }).domande.map((testo, i) => {
      const riga = document.createElement('label');
      riga.className = 'ai-scrivi-domanda';
      const t = document.createElement('span'); t.textContent = testo;
      const area = document.createElement('textarea');
      area.className = 'ui-input'; area.rows = 2; area.dataset.risposta = String(i);
      riga.append(t, area);
      return riga;
    }));
    fase('domande');
    const prima = contenitore.querySelector('textarea');
    if (prima) prima.focus();
  };

  // Avvia il lavoro e aspetta l'esito: url + dati del POST, poi la fase in cui mostrare il testo.
  const lavora = async (url, dati, dopo, indietro) => {
    sbaglio('');
    const giro = ++stato.giro;
    fase('attesa');
    try {
      const r = await fetch(url, { method: 'POST', body: dati, headers: { 'X-CSRFToken': csrf() } });
      const avvio = await r.json();
      if (!r.ok) throw new Error(avvio.errore || 'Non è stato possibile avviare Ada.');
      const inizio = Date.now();
      while (giro === stato.giro && dialogo.open) {
        await new Promise((fatto) => setTimeout(fatto, 1500));
        const e = await (await fetch(avvio.esito)).json();
        if (e.in_corso) {
          if (Date.now() - inizio > 180000) throw new Error('Ada ci sta mettendo troppo: riprova tra poco.');
          continue;
        }
        if (e.errore) throw new Error(e.errore);
        q('[data-bozza]').value = e.bozza;
        q('[data-note]').hidden = !e.note;
        q('[data-note-testo]').textContent = e.note || '';
        fase(dopo);
        q('[data-bozza]').focus();
        return;
      }
    } catch (err) {
      if (giro !== stato.giro) return;
      sbaglio(err.message);
      fase(indietro);
    }
  };

  const scrivi = (testoDaMigliorare) => {
    const dati = new FormData();
    dati.append('testo', testoDaMigliorare || '');
    const risposte = {};
    dialogo.querySelectorAll('[data-risposta]').forEach((a) => { risposte[a.dataset.risposta] = a.value; });
    dati.append('risposte', JSON.stringify(testoDaMigliorare ? {} : risposte));
    lavora(script.dataset.url.replace('CAMPO', stato.chiave), dati, 'bozza', testoDaMigliorare ? 'scelta' : 'domande');
  };

  const etichettaDi = (campo) => {
    if (campo.dataset.etichetta) return campo.dataset.etichetta;
    const l = campo.id && document.querySelector(`label[for="${CSS.escape(campo.id)}"]`);
    return l ? l.textContent.trim() : (campo.name || '');
  };
  const scriviLibero = (istruzione) => {
    const dati = new FormData();
    dati.append('testo', stato.campo.value);
    dati.append('istruzione', istruzione);
    dati.append('etichetta', etichettaDi(stato.campo));
    const rec = stato.campo.dataset.record || (stato.campo.closest('[data-record]') || {}).dataset?.record || '';
    dati.append('record', rec);
    lavora(script.dataset.url.replace('CAMPO', 'libero'), dati, 'bozza_libero', 'istruzione');
  };

  const apri = (campo) => {
    const chiave = campo.dataset.scriviConAda || 'libero';
    stato = { campo, chiave, giro: stato.giro + 1, modo: 'campo', nota: '' };
    titolo.textContent = 'Scrivi con Ada';
    q('[data-bozza-etichetta]').textContent = 'Proposta (puoi modificarla prima di usarla)';
    sbaglio('');
    if (chiave === 'libero') {
      q('[data-istruzione]').value = '';
      q('[data-istruzione-guida]').textContent = campo.value.trim()
        ? 'Che cosa deve fare Ada con questo testo? Vedrai la proposta prima che entri nel campo.'
        : 'Il campo è vuoto: scrivi che cosa vuoi, Ada prepara il testo. Vedrai la proposta prima che entri nel campo.';
      dialogo.querySelectorAll('[data-rapida]').forEach((b) => { b.hidden = !campo.value.trim(); });
      fase('istruzione');
      dialogo.showModal();
      q('[data-istruzione]').focus();
      return;
    }
    if (campo.value.trim()) fase('scelta'); else mostraDomande();
    dialogo.showModal();
  };

  const riassumi = (bottone) => {
    stato = { campo: null, chiave: '', giro: stato.giro + 1, modo: 'riassunto', nota: bottone.dataset.nota || '' };
    titolo.textContent = 'Riassunto di Ada';
    q('[data-bozza-etichetta]').textContent = 'Riassunto (puoi modificarlo prima di salvarlo come nota)';
    sbaglio('');
    dialogo.showModal();
    lavora(bottone.dataset.riassumi, new FormData(), 'riassunto', 'riassunto');
  };

  const metti = (testo, inCoda) => {
    const c = stato.campo;
    c.value = inCoda && c.value.trim() ? `${c.value.replace(/\s+$/, '')}\n\n${testo}` : testo;
    c.dispatchEvent(new Event('input', { bubbles: true }));
    c.dispatchEvent(new Event('change', { bubbles: true }));
    dialogo.close();
    c.focus();
  };

  dialogo.addEventListener('click', async (e) => {
    const rapida = e.target.closest('[data-rapida]');
    if (rapida) { scriviLibero(rapida.dataset.rapida); return; }
    const b = e.target.closest('[data-azione]');
    if (!b) return;
    const azione = b.dataset.azione;
    if (azione === 'domande') mostraDomande();
    if (azione === 'scrivi') scrivi('');
    if (azione === 'migliora') scrivi(stato.campo.value);
    if (azione === 'libero') {
      const testo = q('[data-istruzione]').value.trim();
      if (!testo) { sbaglio('Scrivi che cosa vuoi, o scegli un\'istruzione rapida.'); return; }
      scriviLibero(testo);
    }
    if (azione === 'usa') metti(q('[data-bozza]').value, false);
    if (azione === 'aggiungi') metti(q('[data-bozza]').value, true);
    if (azione === 'copia') {
      try { await navigator.clipboard.writeText(q('[data-bozza]').value); b.textContent = 'Copiato'; setTimeout(() => { b.textContent = 'Copia'; }, 1500); }
      catch (_) { q('[data-bozza]').select(); }
    }
    if (azione === 'nota' && stato.nota) {
      const dati = new FormData();
      dati.append('corpo', `Riassunto di Ada:\n${q('[data-bozza]').value}`);
      dati.append('tipo', 'nota');
      const r = await fetch(stato.nota, { method: 'POST', body: dati, headers: { 'X-CSRFToken': csrf(), 'HX-Request': 'true' } });
      if (!r.ok) { sbaglio('Non sono riuscito a salvare la nota.'); return; }
      const pannello = document.getElementById('chatter');
      if (pannello) {
        pannello.outerHTML = await r.text();
        const nuovo = document.getElementById('chatter');
        if (window.htmx && nuovo) window.htmx.process(nuovo);
      }
      dialogo.close();
    }
  });
  dialogo.addEventListener('close', () => { stato.giro += 1; });   // una bozza in arrivo dopo la chiusura non tocca nulla

  const SELETTORE = 'textarea[data-scrivi-con-ada], form[data-bozza] textarea';
  const prepara = (radice) => {
    radice.querySelectorAll(SELETTORE).forEach((campo) => {
      if (campo.dataset.scriviPronto || campo.readOnly || campo.disabled || campo.dataset.scriviConAda === 'no') return;
      campo.dataset.scriviPronto = '1';
      const bottone = document.createElement('button');
      bottone.type = 'button';
      bottone.className = 'ui-btn ui-btn-ghost ui-btn-sm ai-scrivi-btn';
      bottone.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l2.2 6.3L20.5 10l-6.3 2.2L12 18.5l-2.2-6.3L3.5 10l6.3-1.7z"/></svg><span>Scrivi con Ada</span>';
      bottone.addEventListener('click', () => apri(campo));
      campo.insertAdjacentElement('afterend', bottone);
    });
  };
  prepara(document);
  document.addEventListener('htmx:load', (e) => prepara(e.target));        // il chatter si ridisegna con HTMX
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-riassumi]');
    if (b) riassumi(b);
  });
})();
