// Editor dei modelli di email: anteprima dal vivo (dal server, che fa l'escape), campi cliccabili, prova a se stessi.
(() => {
  const radice = document.querySelector('[data-editor]');
  if (!radice) return;
  const form = radice.querySelector('[data-editor-form]');
  const oggetto = form.elements.oggetto;
  const corpo = form.elements.corpo;
  const errore = radice.querySelector('[data-editor-errore]');
  let ultimo = corpo;

  const dati = () => {
    const d = new FormData();
    d.append('csrfmiddlewaretoken', form.elements.csrfmiddlewaretoken.value);
    d.append('codice', radice.dataset.codice);
    d.append('dominio', radice.dataset.dominio);
    d.append('oggetto', oggetto.value);
    d.append('corpo', corpo.value);
    return d;
  };

  const aggiorna = async () => {
    const r = await fetch(radice.dataset.anteprima, { method: 'POST', body: dati(), credentials: 'same-origin' });
    if (!r.ok) return;
    const { oggetto: titolo, html, sconosciuti } = await r.json();
    radice.querySelector('[data-editor-oggetto]').textContent = titolo;
    radice.querySelector('[data-editor-iframe]').srcdoc = html;
    errore.hidden = !sconosciuti.length;
    errore.textContent = sconosciuti.length ? `Questi campi non esistono: ${sconosciuti.join(', ')}` : '';
  };

  let attesa;
  const programma = () => { clearTimeout(attesa); attesa = setTimeout(aggiorna, 300); };
  [oggetto, corpo].forEach((c) => {
    c.addEventListener('input', programma);
    c.addEventListener('focus', () => { ultimo = c; });
  });
  radice.querySelectorAll('[data-inserisci]').forEach((b) => b.addEventListener('click', () => {
    const testo = `{{ ${b.dataset.inserisci} }}`;
    const da = ultimo.selectionStart ?? ultimo.value.length;
    ultimo.setRangeText(testo, da, ultimo.selectionEnd ?? da, 'end');
    ultimo.focus();
    programma();
  }));
  const prova = radice.querySelector('[data-editor-prova]');
  if (prova) prova.addEventListener('click', async () => {
    const r = await fetch(radice.dataset.prova, { method: 'POST', body: dati(), credentials: 'same-origin' });
    const esito = r.ok ? await r.json() : { ok: false, errore: 'Invio non riuscito' };
    window.uiToast(esito.ok ? `Prova mandata a ${esito.a}` : esito.errore);
  });
  aggiorna();
})();
