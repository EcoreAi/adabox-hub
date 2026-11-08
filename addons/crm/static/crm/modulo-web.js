/* Modulo «contattaci» di adabox da incorporare in un sito qualsiasi.
   <div data-adabox-lead="https://…/crm/modulo/CHIAVE/" data-telefono data-azienda data-privacy="https://…"></div>
   Nessuna dipendenza; lo stile è minimo e si sovrascrive con le classi .adabox-lead-*. */
(function () {
  'use strict';
  const campo = (nome, etichetta, tipo, obbligatorio) => {
    const id = 'adabox-' + nome + '-' + Math.random().toString(36).slice(2, 8);
    const box = document.createElement('div');
    box.className = 'adabox-lead-campo';
    const lab = document.createElement('label');
    lab.htmlFor = id; lab.textContent = etichetta + (obbligatorio ? ' *' : '');
    const input = document.createElement(tipo === 'textarea' ? 'textarea' : 'input');
    if (tipo !== 'textarea') input.type = tipo;
    input.name = nome; input.id = id; if (obbligatorio) input.required = true;
    if (tipo === 'textarea') input.rows = 4;
    box.append(lab, input);
    return box;
  };
  const stile = '.adabox-lead{display:grid;gap:10px;max-width:480px;font:inherit}.adabox-lead-campo{display:grid;gap:4px}' +
    '.adabox-lead input,.adabox-lead textarea{font:inherit;padding:8px 10px;border:1px solid #c7c7cc;border-radius:8px}' +
    '.adabox-lead button{font:inherit;padding:10px 16px;border:0;border-radius:8px;background:#1e3a8a;color:#fff;cursor:pointer;justify-self:start}' +
    '.adabox-lead-esca{position:absolute;left:-9999px}.adabox-lead-esito{margin:0}.adabox-lead-errore{color:#c4271f}';
  let stileMesso = false;
  document.querySelectorAll('[data-adabox-lead]').forEach((posto) => {
    if (!stileMesso) { const s = document.createElement('style'); s.textContent = stile; document.head.appendChild(s); stileMesso = true; }
    const form = document.createElement('form');
    form.className = 'adabox-lead'; form.noValidate = false;
    form.append(campo('nome', 'Nome', 'text', true), campo('email', 'Email', 'email', true));
    if (posto.hasAttribute('data-telefono')) form.append(campo('telefono', 'Telefono', 'tel', false));
    if (posto.hasAttribute('data-azienda')) form.append(campo('azienda', 'Azienda', 'text', false));
    form.append(campo('messaggio', 'Messaggio', 'textarea', false));
    const esca = document.createElement('input');                      // lo compila solo un bot
    esca.name = 'sito_web'; esca.tabIndex = -1; esca.autocomplete = 'off'; esca.className = 'adabox-lead-esca'; esca.setAttribute('aria-hidden', 'true');
    form.append(esca);
    if (posto.dataset.privacy) {
      const p = document.createElement('p'); p.className = 'adabox-lead-privacy';
      const a = document.createElement('a'); a.href = posto.dataset.privacy; a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'informativa sulla privacy';
      p.append('Inviando accetti l\'', a, '.'); form.append(p);
    }
    const bottone = document.createElement('button'); bottone.type = 'submit'; bottone.textContent = 'Invia';
    const esito = document.createElement('p'); esito.className = 'adabox-lead-esito'; esito.setAttribute('role', 'status');
    form.append(bottone, esito);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const dati = new FormData(form);
      const qs = new URLSearchParams(location.search);
      dati.append('pagina', location.href.slice(0, 300));
      ['utm_source', 'utm_medium', 'utm_campaign'].forEach((k) => { if (qs.get(k)) dati.append(k, qs.get(k)); });
      bottone.disabled = true; esito.textContent = ''; esito.classList.remove('adabox-lead-errore');
      try {
        const r = await fetch(posto.dataset.adaboxLead, { method: 'POST', body: dati });
        const j = await r.json();
        if (!j.ok) throw new Error(j.errore || 'invio non riuscito');
        form.replaceChildren(Object.assign(document.createElement('p'), { className: 'adabox-lead-esito', textContent: j.grazie }));
      } catch (err) {
        esito.textContent = 'Non è stato possibile inviare: ' + err.message + '.'; esito.classList.add('adabox-lead-errore');
        bottone.disabled = false;
      }
    });
    posto.replaceChildren(form);
  });
})();
