/* «Scrivi con Ada» accanto ai campi di istruzioni: intervista (campo vuoto) o miglioramento (campo scritto).
   La bozza va nel campo solo con «Usa questo testo»; si salva con il form, come sempre. */
(function () {
  const campi = [...document.querySelectorAll('textarea[data-scrivi-con-ada]')];
  const dialogo = document.getElementById('ai-scrivi');
  const script = document.currentScript || document.querySelector('script[src*="scrivi_con_ada.js"]');
  if (!campi.length || !dialogo || !script) return;
  const domandePer = JSON.parse(document.getElementById('ai-scrivi-campi').textContent);
  const csrf = (document.querySelector('input[name="csrfmiddlewaretoken"]') || {}).value
    || (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';
  const q = (sel) => dialogo.querySelector(sel);
  const errore = q('[data-scrivi-errore]');
  let stato = { campo: null, chiave: '', giro: 0 };

  const fase = (nome) => {
    dialogo.querySelectorAll('[data-fase]').forEach((s) => { s.hidden = s.dataset.fase !== nome; });
    const vedi = { domande: ['scrivi'], scelta: ['migliora', 'domande'], attesa: [], bozza: ['usa', 'domande'] }[nome];
    dialogo.querySelectorAll('[data-azione]').forEach((b) => { b.hidden = !vedi.includes(b.dataset.azione); });
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

  const scrivi = async (testoDaMigliorare) => {
    sbaglio('');
    const giro = ++stato.giro;
    const dati = new FormData();
    dati.append('testo', testoDaMigliorare || '');
    const risposte = {};
    dialogo.querySelectorAll('[data-risposta]').forEach((a) => { risposte[a.dataset.risposta] = a.value; });
    dati.append('risposte', JSON.stringify(testoDaMigliorare ? {} : risposte));
    fase('attesa');
    try {
      const r = await fetch(script.dataset.url.replace('CAMPO', stato.chiave), { method: 'POST', body: dati, headers: { 'X-CSRFToken': csrf } });
      const avvio = await r.json();
      if (!r.ok) throw new Error(avvio.errore || 'Non è stato possibile avviare la bozza.');
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
        fase('bozza');
        q('[data-bozza]').focus();
        return;
      }
    } catch (err) {
      if (giro !== stato.giro) return;
      sbaglio(err.message);
      fase(testoDaMigliorare ? 'scelta' : 'domande');
    }
  };

  const apri = (campo) => {
    stato = { campo, chiave: campo.dataset.scriviConAda, giro: stato.giro + 1 };
    sbaglio('');
    if (campo.value.trim()) fase('scelta'); else mostraDomande();
    dialogo.showModal();
  };

  dialogo.addEventListener('click', (e) => {
    const b = e.target.closest('[data-azione]');
    if (!b) return;
    if (b.dataset.azione === 'domande') mostraDomande();
    if (b.dataset.azione === 'scrivi') scrivi('');
    if (b.dataset.azione === 'migliora') scrivi(stato.campo.value);
    if (b.dataset.azione === 'usa') {
      stato.campo.value = q('[data-bozza]').value;
      stato.campo.dispatchEvent(new Event('input', { bubbles: true }));
      stato.campo.dispatchEvent(new Event('change', { bubbles: true }));
      dialogo.close();
      stato.campo.focus();
    }
  });
  dialogo.addEventListener('close', () => { stato.giro += 1; });   // una bozza in arrivo dopo la chiusura non tocca nulla

  campi.forEach((campo) => {
    const bottone = document.createElement('button');
    bottone.type = 'button';
    bottone.className = 'ui-btn ui-btn-ghost ui-btn-sm ai-scrivi-btn';
    bottone.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l2.2 6.3L20.5 10l-6.3 2.2L12 18.5l-2.2-6.3L3.5 10l6.3-1.7z"/></svg><span>Scrivi con Ada</span>';
    bottone.addEventListener('click', () => apri(campo));
    campo.insertAdjacentElement('afterend', bottone);
  });
})();
