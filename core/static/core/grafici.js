// Grafici con Chart.js, con le regole di casa: una tinta sola per barre e linee, tavolozza fissa (mai ciclica) per le
// torte con «Altro» oltre la quinta fetta e il totale al centro, marchi sottili, tooltip su tutto, griglia discreta,
// animazioni spente se l'utente le ha ridotte nel sistema. Tipi: barre, barre_orizzontali, linee, area, torta e
// previsione (storia, mediana tratteggiata, fascia 10-90 % e il segno di «oggi»).
window.adaboxGrafici = (function () {
  const stile = getComputedStyle(document.documentElement);
  const tinta = stile.getPropertyValue('--ui-primary').trim() || '#1e3a8a';
  const testo = stile.getPropertyValue('--ui-text').trim() || '#111827';
  const testo2 = stile.getPropertyValue('--ui-text-2').trim() || '#6b7280';
  const bordo = stile.getPropertyValue('--ui-border').trim() || '#e5e5ea';
  const carattere = stile.fontFamily || 'system-ui, sans-serif';
  const TAVOLOZZA = ['#4338ca', '#db2777', '#0369a1', '#7c3aed', '#15803d'];
  const ALTRO = '#94a3b8';
  const FUTURO = '#db2777';
  const TIPI = ['barre', 'barre_orizzontali', 'linee', 'area', 'torta'];
  const ridotto = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fmt = (v) => Number(v).toLocaleString('it-IT', { maximumFractionDigits: 2 });

  const fette = (etichette, valori) => {
    const coppie = etichette.map((e, i) => [e, valori[i]]).filter(([, v]) => v > 0);
    if (coppie.length <= TAVOLOZZA.length) return coppie;
    coppie.sort((a, b) => b[1] - a[1]);
    const prime = coppie.slice(0, TAVOLOZZA.length - 1);
    return [...prime, ['Altro', coppie.slice(TAVOLOZZA.length - 1).reduce((s, [, v]) => s + v, 0)]];
  };
  const sfumatura = (canvas, colore, forza) => {
    const g = canvas.getContext('2d').createLinearGradient(0, 0, 0, canvas.clientHeight || 300);
    const [r, gg, b] = colore;
    g.addColorStop(0, `rgba(${r}, ${gg}, ${b}, ${forza})`); g.addColorStop(1, `rgba(${r}, ${gg}, ${b}, 0)`);
    return g;
  };
  const rgb = (hex) => {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
    return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [30, 58, 138];
  };
  const TINTA = rgb(tinta);

  // il totale al centro della ciambella
  const centro = { id: 'adaboxCentro', afterDraw(chart) {
    const t = chart.options.centro;
    if (!t) return;
    const { ctx, chartArea: a } = chart;
    const x = (a.left + a.right) / 2, y = (a.top + a.bottom) / 2;
    ctx.save(); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = `700 ${Math.max(14, Math.min(22, (a.bottom - a.top) / 9))}px ${carattere}`; ctx.fillStyle = testo; ctx.fillText(t.valore, x, y - 7);
    ctx.font = `500 11px ${carattere}`; ctx.fillStyle = testo2; ctx.fillText(t.etichetta, x, y + 12);
    ctx.restore();
  } };
  // il confine tra storia e previsione
  const oggi = { id: 'adaboxOggi', afterDatasetsDraw(chart) {
    const n = chart.options.oggi;
    if (!n) return;
    const x = chart.scales.x.getPixelForValue(n - 0.5);
    const { top, bottom } = chart.chartArea;
    const ctx = chart.ctx;
    ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = testo2; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
    ctx.setLineDash([]); ctx.font = `500 11px ${carattere}`; ctx.fillStyle = testo2; ctx.textAlign = 'center';
    ctx.fillText('oggi', x, top + 10);
    ctx.restore();
  } };

  const asseCategorie = { grid: { display: false }, border: { color: bordo }, ticks: { color: testo2, maxRotation: 0, autoSkip: true, font: { size: 11 } } };
  const asseValori = { beginAtZero: true, grid: { color: bordo }, border: { display: false }, ticks: { color: testo2, font: { size: 11 }, callback: (v) => fmt(v) } };

  function disegna(canvas, serie) {
    if (!window.Chart) return null;
    const comune = { responsive: true, maintainAspectRatio: false, animation: ridotto ? false : { duration: 700, easing: 'easeOutQuart' } };
    if (serie.tipo === 'previsione') return previsione(canvas, serie, comune);
    if (serie.tipo === 'torta') {
      const coppie = fette(serie.etichette, serie.valori);
      const totale = coppie.reduce((s, [, v]) => s + v, 0);
      return new Chart(canvas, {
        type: 'doughnut',
        data: { labels: coppie.map(([e]) => e), datasets: [{ data: coppie.map(([, v]) => v), borderColor: '#fff', borderWidth: 2, hoverOffset: 6,
          backgroundColor: coppie.map(([e], i) => (e === 'Altro' ? ALTRO : TAVOLOZZA[i])) }] },
        options: { ...comune, cutout: '62%', centro: { valore: fmt(totale), etichetta: 'totale' }, plugins: {
          legend: { display: true, position: 'right', labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 8, color: testo2, font: { size: 12 } } },
          tooltip: { callbacks: { label: (c) => ` ${fmt(c.parsed)} (${totale ? Math.round(c.parsed * 100 / totale) : 0}%)` } } } },
        plugins: [centro],
      });
    }
    const linee = serie.tipo === 'linee' || serie.tipo === 'area';
    const area = serie.tipo === 'area';
    const orizzontale = serie.tipo === 'barre_orizzontali';
    return new Chart(canvas, {
      type: linee ? 'line' : 'bar',
      data: { labels: serie.etichette, datasets: [{ data: serie.valori, borderColor: tinta, backgroundColor: linee ? sfumatura(canvas, TINTA, area ? 0.4 : 0.22) : tinta,
        borderWidth: linee ? 2 : 0, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 28, tension: area ? 0.4 : 0.3, fill: linee,
        pointRadius: area ? 0 : 3, pointHoverRadius: 6, pointBackgroundColor: '#fff', pointBorderWidth: 2 }] },
      options: { ...comune, indexAxis: orizzontale ? 'y' : 'x', interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${fmt(orizzontale ? c.parsed.x : c.parsed.y)}` } } },
        scales: orizzontale ? { x: asseValori, y: asseCategorie } : { x: asseCategorie, y: asseValori } },
    });
  }

  function previsione(canvas, serie, comune) {
    const storico = serie.storico || [], futuro = serie.futuro || [];
    const n = storico.length;
    if (!n) return null;
    const ultimo = storico[n - 1][1];
    const vuoti = Array(n - 1).fill(null);
    const colore = rgb(FUTURO);
    return new Chart(canvas, {
      type: 'line',
      data: { labels: [...storico.map((s) => s[0]), ...futuro.map((f) => f[0])], datasets: [
        { label: 'Storia', data: [...storico.map((s) => s[1]), ...futuro.map(() => null)], borderColor: tinta, backgroundColor: sfumatura(canvas, TINTA, 0.22),
          borderWidth: 2.5, tension: 0.3, fill: true, pointRadius: 2, pointHoverRadius: 6, pointBackgroundColor: '#fff', pointBorderWidth: 2 },
        { label: 'Previsione', data: [...vuoti, ultimo, ...futuro.map((f) => f[2])], borderColor: FUTURO, borderDash: [6, 4], borderWidth: 2.5, tension: 0.3,
          fill: false, pointRadius: 3.5, pointHoverRadius: 7, pointBackgroundColor: '#fff', pointBorderColor: FUTURO, pointBorderWidth: 2, previsione: true },
        { label: 'Fascia 10–90 %', data: [...vuoti, ultimo, ...futuro.map((f) => f[3])], borderColor: 'transparent', pointRadius: 0, pointHoverRadius: 0,
          backgroundColor: `rgba(${colore[0]}, ${colore[1]}, ${colore[2]}, .14)`, fill: '+1', tension: 0.3 },
        { label: '_basso', data: [...vuoti, ultimo, ...futuro.map((f) => f[1])], borderColor: 'transparent', pointRadius: 0, pointHoverRadius: 0, fill: false, tension: 0.3 },
      ] },
      options: { ...comune, oggi: n, interaction: { mode: 'index', intersect: false }, plugins: {
        legend: { display: true, position: 'bottom', labels: { usePointStyle: true, boxWidth: 8, color: testo2, font: { size: 12 }, filter: (i) => !i.text.startsWith('_') } },
        tooltip: { filter: (i) => i.dataset.label === 'Storia' ? i.dataIndex < n : i.dataset.previsione && i.dataIndex >= n,
          callbacks: { label: (c) => {
            if (!c.dataset.previsione) return ` ${fmt(c.parsed.y)}`;
            const f = futuro[c.dataIndex - n];
            return f ? ` previsione ${fmt(f[2])} (10–90 %: ${fmt(f[1])} – ${fmt(f[3])})` : ` ${fmt(c.parsed.y)}`;
          } } } },
        scales: { x: asseCategorie, y: asseValori } },
      plugins: [oggi],
    });
  }

  // ridisegna un canvas con una serie nuova (es. cambio di tipo)
  function ridisegna(canvas, serie) {
    const g = window.Chart && Chart.getChart(canvas);
    if (g) g.destroy();
    canvas.dataset.disegnato = '1';
    return disegna(canvas, serie);
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
  document.addEventListener('htmx:afterSettle', (e) => tutti(e.target));     // le card ricaricate si ridisegnano
  return { disegna, ridisegna, tutti, TIPI };
})();
