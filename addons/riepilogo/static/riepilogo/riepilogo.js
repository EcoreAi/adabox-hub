// Riepilogo: la finestra si chiude con la X, con Esc o cliccando fuori; appena si apre, il fuoco va sulla X.
(function () {
  const contenitore = () => document.getElementById('rp-pannello');
  // Il contenitore nasce nella barra in alto, che con il suo backdrop-filter terrebbe la finestra dentro i suoi 60px:
  // va in fondo al body, così «position: fixed» vale per tutto lo schermo.
  const c = contenitore();
  if (c && c.parentElement !== document.body) document.body.appendChild(c);
  const chiudi = () => { const c = contenitore(); if (c && c.firstChild) c.replaceChildren(); };
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-rp-chiudi]') || (e.target.classList && e.target.classList.contains('rp-modal'))) chiudi();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') chiudi(); });
  document.addEventListener('htmx:afterSwap', (e) => {
    if (e.target && e.target.id === 'rp-pannello') { const x = e.target.querySelector('[data-rp-chiudi]'); if (x) x.focus(); }
  });
})();
