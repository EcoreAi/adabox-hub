/* cambia_azienda.js — cambio di azienda in un clic. Un link <a href="…" data-cambia-azienda="<pk>"> rende corrente
   quell'azienda e apre il link: lo script scrive azienda e next (l'href) nel form nascosto di
   theme/partials/_cambia_azienda.html e lo invia (POST a core:cambia_azienda, che reindirizza a next).
   Tasto centrale, Ctrl/Cmd/Shift/Alt, un target diverso dalla scheda o una pagina senza script: si segue il link, e
   la pagina dell'altra azienda risponde «Passa a …». Delegato sul documento: vale anche per i link arrivati dopo il
   caricamento (HTMX). */
(function () {
  'use strict';
  document.addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    const link = e.target instanceof Element ? e.target.closest('a[data-cambia-azienda]') : null;
    if (!link || (link.target && link.target !== '_self')) return;
    const form = document.querySelector('form[data-cambia-azienda-form]');
    if (!form) return;                                    // pagina senza il form: si segue il link
    e.preventDefault();
    form.elements.azienda.value = link.dataset.cambiaAzienda;
    form.elements.next.value = link.getAttribute('href');
    form.submit();
  });
})();
