// Dashboard: numeri che salgono, tabella sotto il grafico, e il modo «Personalizza»: trascina, sposta con le frecce,
// allarga, togli e rimetti i widget. Ogni cambiamento si salva da solo.
(function () {
  const griglia = document.getElementById('wd-griglia');
  const csrf = (document.querySelector('input[name=csrfmiddlewaretoken]') || {}).value;
  const ridotto = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // --- numeri che salgono fino al valore (solo se il testo comincia con un numero) ---
  document.querySelectorAll('[data-contatore]').forEach((el) => {
    const m = el.textContent.trim().match(/^(\d{1,3}(?:\.\d{3})*|\d+)(,\d+)?(.*)$/);
    if (!m) return;
    const fine = parseFloat(m[1].replace(/\./g, '') + (m[2] ? m[2].replace(',', '.') : ''));
    el.classList.toggle('is-zero', fine === 0);       // gli zeri restano in secondo piano: l'occhio va ai numeri veri
    if (ridotto || fine === 0) return;
    const decimali = m[2] ? m[2].length - 1 : 0;
    const inizio = performance.now();
    const passo = (t) => {
      const q = Math.min(1, (t - inizio) / 900);
      const v = fine * (1 - Math.pow(1 - q, 3));
      el.textContent = v.toLocaleString('it-IT', { minimumFractionDigits: decimali, maximumFractionDigits: decimali }) + m[3];
      if (q < 1) requestAnimationFrame(passo);
    };
    requestAnimationFrame(passo);
  });

  // --- tabella sotto il grafico ---
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-tabella]');
    if (!b) return;
    const tab = document.getElementById(b.getAttribute('aria-controls'));
    const aperta = tab.hidden;
    tab.hidden = !aperta;
    b.setAttribute('aria-pressed', String(aperta));
  });

  if (!griglia) return;
  const modifica = document.getElementById('wd-modifica');
  const aiuto = document.getElementById('wd-aiuto');
  const cassetto = document.getElementById('wd-cassetto');
  const bottoneAggiungi = document.getElementById('wd-aggiungi');
  const ripristina = document.getElementById('wd-ripristina');

  // --- salvataggio ---
  let timer = null;
  const aggiunti = [];
  const stato = () => ({
    widget: [...[...griglia.querySelectorAll('.wd-widget')].map((w) => ({ id: w.dataset.id, w: parseInt(w.dataset.w, 10) })), ...aggiunti.map((id) => ({ id }))],
    nascosti: [...cassetto.querySelectorAll('[data-aggiungi]')].map((b) => b.dataset.aggiungi),
  });
  const salva = (poi) => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const r = await fetch(griglia.dataset.salva, { method: 'POST', credentials: 'same-origin', body: JSON.stringify(stato()),
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf } });
        if (!r.ok) throw new Error();
        if (ripristina) ripristina.hidden = false;
        if (poi) poi(); else if (window.uiToast) window.uiToast('Dashboard salvata');
      } catch (e) { if (window.uiToast) window.uiToast('Non sono riuscito a salvare la dashboard', 'warn'); }
    }, poi ? 0 : 400);
  };

  // --- modo personalizza ---
  modifica.addEventListener('click', () => {
    const attivo = !griglia.classList.contains('is-modifica');
    griglia.classList.toggle('is-modifica', attivo);
    modifica.setAttribute('aria-pressed', String(attivo));
    modifica.classList.toggle('ui-btn-primary', attivo);
    aiuto.hidden = !attivo;
    if (!attivo) cassetto.hidden = true;
  });

  const aggiornaCassetto = () => {
    const n = cassetto.querySelectorAll('[data-aggiungi]').length;
    document.getElementById('wd-nascosti-n').textContent = n;
    cassetto.querySelector('.wd-cassetto-vuoto').hidden = n > 0;
  };
  bottoneAggiungi.addEventListener('click', () => {
    cassetto.hidden = !cassetto.hidden;
    if (!cassetto.hidden) cerca.focus();
  });
  const cerca = document.getElementById('wd-cassetto-cerca');
  cerca.addEventListener('input', () => {
    const testo = cerca.value.trim().toLowerCase();
    cassetto.querySelectorAll('#wd-cassetto-voci li').forEach((li) => { li.hidden = !li.textContent.toLowerCase().includes(testo); });
  });
  cassetto.addEventListener('click', (e) => {
    if (e.target.closest('[data-chiudi-cassetto]')) { cassetto.hidden = true; return; }
    const b = e.target.closest('[data-aggiungi]');
    if (!b) return;
    aggiunti.push(b.dataset.aggiungi);
    b.closest('li').remove();
    aggiornaCassetto();
    salva(() => window.location.reload());     // il widget nuovo lo disegna il server
  });

  griglia.addEventListener('click', (e) => {
    const w = e.target.closest('.wd-widget');
    if (!w || !griglia.classList.contains('is-modifica')) return;
    const sposta = e.target.closest('[data-sposta]');
    if (sposta) {
      const indietro = parseInt(sposta.dataset.sposta, 10) < 0;
      const altro = indietro ? w.previousElementSibling : w.nextElementSibling;
      if (altro) { indietro ? altro.before(w) : altro.after(w); salva(); }
      sposta.focus();
      return;
    }
    if (e.target.closest('[data-larghezza]')) {
      const n = (parseInt(w.dataset.w, 10) % 4) + 1;
      w.dataset.w = n; w.style.setProperty('--w', n);
      w.querySelector('[data-larghezza] span').textContent = n;
      if (window.Chart) w.querySelectorAll('canvas').forEach((c) => { const g = Chart.getChart(c); if (g) g.resize(); });
      salva();
      return;
    }
    if (e.target.closest('[data-nascondi]')) {
      const li = document.createElement('li');
      li.innerHTML = '<button type="button"><strong></strong><small>tolto adesso</small></button>';
      li.querySelector('button').dataset.aggiungi = w.dataset.id;
      li.querySelector('strong').textContent = w.getAttribute('aria-label');
      cassetto.querySelector('#wd-cassetto-voci').append(li);
      w.remove();
      aggiornaCassetto();
      salva();
    }
  });

  // --- trascinamento da un punto qualsiasi del widget: una copia del widget segue il puntatore, il widget vero resta nella griglia come
  //     segnaposto e si infila al posto di quello su cui si passa (dopo se si va avanti, prima se si torna indietro).
  //     Si ascolta sul documento, come nel kanban: la presa non si perde quando il widget cambia posto nel DOM
  //     né quando il puntatore esce dalla griglia; Esc rimette tutto com'era.
  const SOGLIA = 4;
  let presa = null;
  const inizia = (e) => {
    const r = presa.widget.getBoundingClientRect();
    presa.dx = presa.x - r.left; presa.dy = presa.y - r.top;
    presa.volante = presa.widget.cloneNode(true);
    presa.volante.classList.add('wd-volante');
    Object.assign(presa.volante.style, { position: 'fixed', left: '0', top: '0', width: `${r.width}px`, height: `${r.height}px`, margin: '0' });
    // la copia di un canvas nasce bianca: ci si ridisegna sopra il grafico
    const copie = presa.volante.querySelectorAll('canvas');
    presa.widget.querySelectorAll('canvas').forEach((c, i) => {
      try { copie[i].width = c.width; copie[i].height = c.height; copie[i].getContext('2d').drawImage(c, 0, 0); } catch (err) { /* la copia va bene anche senza */ }
    });
    griglia.append(presa.volante);             // dentro la griglia, così tiene gli stili del widget
    presa.widget.classList.add('is-trascinato');
    document.body.classList.add('is-trascinando');
    muovi(e);
  };
  const muovi = (e) => {
    if (!presa) return;
    if (!presa.volante) { if (Math.hypot(e.clientX - presa.x, e.clientY - presa.y) >= SOGLIA) inizia(e); return; }
    e.preventDefault();
    presa.volante.style.transform = `translate(${e.clientX - presa.dx}px, ${e.clientY - presa.dy}px) scale(1.02)`;
    const sotto = document.elementFromPoint(e.clientX, e.clientY);
    const altro = sotto && sotto.closest('.wd-widget');
    if (!altro || altro === presa.widget || altro === presa.volante || altro.parentElement !== griglia) {
      if (!altro || altro === presa.widget) presa.ultimo = null;
      return;
    }
    if (altro === presa.ultimo) return;        // la griglia si è riassestata sotto il puntatore: niente rimbalzi
    presa.ultimo = altro;
    const avanti = Boolean(altro.compareDocumentPosition(presa.widget) & Node.DOCUMENT_POSITION_PRECEDING);
    if (avanti) altro.after(presa.widget); else altro.before(presa.widget);
  };
  const fine = (e, conferma) => {
    if (!presa) return;
    const { widget, volante, genitore, dopo } = presa;
    presa = null;
    document.removeEventListener('pointermove', muovi);
    document.removeEventListener('pointerup', suRilascio);
    document.removeEventListener('pointercancel', suAnnullo);
    document.removeEventListener('keydown', suTasto);
    if (!volante) return;
    volante.remove();
    widget.classList.remove('is-trascinato');
    document.body.classList.remove('is-trascinando');
    if (conferma) salva(); else genitore.insertBefore(widget, dopo);
  };
  const suRilascio = (e) => fine(e, true);
  const suAnnullo = (e) => fine(e, false);
  const suTasto = (e) => { if (e.key === 'Escape') fine(e, false); };
  griglia.addEventListener('pointerdown', (e) => {
    if (!griglia.classList.contains('is-modifica') || e.button !== 0 || presa) return;
    const widget = e.target.closest('.wd-widget');
    if (!widget || (!e.target.closest('.wd-maniglia') && e.target.closest('button, a, input, select, textarea, summary, .an-menu-pannello'))) return;
    e.preventDefault();
    presa = { widget, x: e.clientX, y: e.clientY, volante: null, ultimo: null, genitore: widget.parentElement, dopo: widget.nextElementSibling };
    document.addEventListener('pointermove', muovi);
    document.addEventListener('pointerup', suRilascio);
    document.addEventListener('pointercancel', suAnnullo);
    document.addEventListener('keydown', suTasto);
  });
  griglia.addEventListener('dragstart', (e) => e.preventDefault());
})();
