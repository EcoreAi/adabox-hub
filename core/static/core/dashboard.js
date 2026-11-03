// Dashboard: numeri che salgono, tabella sotto il grafico, e il modo «Personalizza»: trascina, sposta con le frecce,
// allarga, togli e rimetti i widget. Ogni cambiamento si salva da solo.
(function () {
  const griglia = document.getElementById('wd-griglia');
  const csrf = (document.querySelector('input[name=csrfmiddlewaretoken]') || {}).value;
  const ridotto = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // --- numeri che salgono fino al valore (solo se il testo comincia con un numero) ---
  document.querySelectorAll('[data-contatore]').forEach((el) => {
    const m = el.textContent.trim().match(/^(\d{1,3}(?:\.\d{3})*|\d+)(,\d+)?(.*)$/);
    if (!m || ridotto) return;
    const fine = parseFloat(m[1].replace(/\./g, '') + (m[2] ? m[2].replace(',', '.') : ''));
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
  const stato = () => ({
    widget: [...griglia.querySelectorAll('.wd-widget')].map((w) => ({ id: w.dataset.id, w: parseInt(w.dataset.w, 10) })),
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
    bottoneAggiungi.hidden = n === 0;
    cassetto.querySelector('.wd-cassetto-vuoto').hidden = n > 0;
  };
  bottoneAggiungi.addEventListener('click', () => { cassetto.hidden = !cassetto.hidden; });
  cassetto.addEventListener('click', (e) => {
    if (e.target.closest('[data-chiudi-cassetto]')) { cassetto.hidden = true; return; }
    const b = e.target.closest('[data-aggiungi]');
    if (!b) return;
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

  // --- trascinamento dalla maniglia: il widget segue il puntatore e si infila dove lo lasci ---
  let presa = null;
  griglia.addEventListener('pointerdown', (e) => {
    const maniglia = e.target.closest('.wd-maniglia');
    if (!maniglia || !griglia.classList.contains('is-modifica') || e.button !== 0) return;
    e.preventDefault();
    presa = maniglia.closest('.wd-widget');
    presa.classList.add('is-trascinato');
    maniglia.setPointerCapture(e.pointerId);
  });
  griglia.addEventListener('pointermove', (e) => {
    if (!presa) return;
    const sotto = document.elementFromPoint(e.clientX, e.clientY);
    const altro = sotto && sotto.closest('.wd-widget');
    if (!altro || altro === presa || altro.parentElement !== griglia) return;
    const r = altro.getBoundingClientRect();
    const prima = (e.clientX - r.left) / r.width < 0.5 && (e.clientY - r.top) / r.height < 0.75;
    if (prima) altro.before(presa); else altro.after(presa);
  });
  const lascia = () => { if (!presa) return; presa.classList.remove('is-trascinato'); presa = null; salva(); };
  griglia.addEventListener('pointerup', lascia);
  griglia.addEventListener('pointercancel', lascia);
})();
