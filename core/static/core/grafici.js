// Grafici con Chart.js, con le regole di casa: una tinta sola per barre e linee, tavolozza fissa (mai ciclica) per le
// torte con «Altro» oltre la quinta fetta, marchi sottili, tooltip su tutto, griglia discreta, animazioni spente se
// l'utente le ha ridotte nel sistema.
window.adaboxGrafici = (function () {
  const stile = getComputedStyle(document.documentElement);
  const tinta = stile.getPropertyValue('--ui-primary').trim() || '#1e3a8a';
  const testo2 = stile.getPropertyValue('--ui-text-2').trim() || '#6b7280';
  const bordo = stile.getPropertyValue('--ui-border').trim() || '#e5e5ea';
  const TAVOLOZZA = ['#4338ca', '#db2777', '#0369a1', '#7c3aed', '#15803d'];
  const ALTRO = '#94a3b8';
  const ridotto = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fmt = (v) => Number(v).toLocaleString('it-IT', { maximumFractionDigits: 2 });

  const fette = (etichette, valori) => {
    const coppie = etichette.map((e, i) => [e, valori[i]]).filter(([, v]) => v > 0);
    if (coppie.length <= TAVOLOZZA.length) return coppie;
    coppie.sort((a, b) => b[1] - a[1]);
    const prime = coppie.slice(0, TAVOLOZZA.length - 1);
    return [...prime, ['Altro', coppie.slice(TAVOLOZZA.length - 1).reduce((s, [, v]) => s + v, 0)]];
  };
  const sfumatura = (canvas) => {
    const g = canvas.getContext('2d').createLinearGradient(0, 0, 0, canvas.clientHeight || 300);
    g.addColorStop(0, 'rgba(30, 58, 138, .22)'); g.addColorStop(1, 'rgba(30, 58, 138, 0)');
    return g;
  };

  function disegna(canvas, serie) {
    if (!window.Chart) return null;
    const comune = { responsive: true, maintainAspectRatio: false, animation: ridotto ? false : { duration: 700, easing: 'easeOutQuart' } };
    if (serie.tipo === 'torta') {
      const coppie = fette(serie.etichette, serie.valori);
      const totale = coppie.reduce((s, [, v]) => s + v, 0);
      return new Chart(canvas, {
        type: 'doughnut',
        data: { labels: coppie.map(([e]) => e), datasets: [{ data: coppie.map(([, v]) => v), borderColor: '#fff', borderWidth: 2, hoverOffset: 6,
          backgroundColor: coppie.map(([e], i) => (e === 'Altro' ? ALTRO : TAVOLOZZA[i])) }] },
        options: { ...comune, cutout: '58%', plugins: {
          legend: { display: true, position: 'right', labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 8, color: testo2, font: { size: 12 } } },
          tooltip: { callbacks: { label: (c) => ` ${fmt(c.parsed)} (${totale ? Math.round(c.parsed * 100 / totale) : 0}%)` } } } },
      });
    }
    const linee = serie.tipo === 'linee';
    return new Chart(canvas, {
      type: linee ? 'line' : 'bar',
      data: { labels: serie.etichette, datasets: [{ data: serie.valori, borderColor: tinta, backgroundColor: linee ? sfumatura(canvas) : tinta,
        borderWidth: linee ? 2 : 0, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 28, tension: 0.3, fill: linee,
        pointRadius: 3, pointHoverRadius: 6, pointBackgroundColor: '#fff', pointBorderWidth: 2 }] },
      options: { ...comune, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${fmt(c.parsed.y)}` } } },
        scales: { x: { grid: { display: false }, border: { color: bordo }, ticks: { color: testo2, maxRotation: 0, autoSkip: true, font: { size: 11 } } },
          y: { beginAtZero: true, grid: { color: bordo }, border: { display: false }, ticks: { color: testo2, font: { size: 11 }, callback: (v) => fmt(v) } } } },
    });
  }

  function tutti(radice) {
    (radice || document).querySelectorAll('canvas[data-grafico]').forEach((c) => {
      const nodo = document.getElementById(c.dataset.grafico);
      if (!nodo || c.dataset.disegnato) return;
      c.dataset.disegnato = '1';
      try { disegna(c, JSON.parse(nodo.textContent)); } catch (e) { /* un grafico rotto non blocca gli altri */ }
    });
  }
  document.addEventListener('DOMContentLoaded', () => tutti());
  return { disegna, tutti };
})();
