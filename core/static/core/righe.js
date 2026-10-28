// Righe dei documenti: "Aggiungi riga" clona il modello del formset (__prefix__ -> indice) e aggiorna il totale.
(function () {
  document.querySelectorAll('[data-righe]').forEach((sezione) => {
    const prefisso = sezione.dataset.righe;
    const totale = sezione.querySelector(`input[name="${prefisso}-TOTAL_FORMS"]`);
    const corpo = sezione.querySelector('[data-righe-corpo]');
    const modello = sezione.querySelector('template[data-righe-modello]');
    const bottone = sezione.querySelector('[data-aggiungi-riga]');
    if (!totale || !corpo || !modello || !bottone) return;
    bottone.addEventListener('click', () => {
      const indice = parseInt(totale.value, 10);
      const html = modello.innerHTML.replace(/__prefix__/g, String(indice));
      corpo.insertAdjacentHTML('beforeend', html);
      totale.value = String(indice + 1);
      const primo = corpo.lastElementChild.querySelector('input, select, textarea');
      if (primo) primo.focus();
    });
  });
})();
