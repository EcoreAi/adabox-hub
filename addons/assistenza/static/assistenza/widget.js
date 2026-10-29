/*
 * Widget «Segnala un problema» da incollare nell'applicazione del cliente:
 *
 *   <script src="https://HUB/static/assistenza/widget.js" data-chiave="CHIAVE" async></script>
 *
 * Attributi facoltativi: data-versione (versione dell'applicazione), data-email e data-nome (l'utente collegato),
 * data-testo (testo del bottone), data-colore (colore del bottone), data-posizione ("destra" o "sinistra").
 * In alternativa, prima dello script: window.AssistenzaWidget = {email: "...", nome: "...", versione: "..."}.
 *
 * Raccoglie da solo pagina, browser, schermo, lingua e gli ultimi errori JavaScript; lo screenshot si allega da
 * file o si cattura (il browser chiede il permesso). Tutto sta in uno shadow DOM: niente conflitti di stile.
 */
(function () {
  'use strict';
  var script = document.currentScript;
  if (!script || !script.dataset.chiave || window.__assistenzaWidget) return;
  window.__assistenzaWidget = true;

  var config = window.AssistenzaWidget || {};
  var d = script.dataset;
  var base = new URL(script.src).origin;
  var endpoint = base + '/assistenza/widget/' + encodeURIComponent(d.chiave) + '/';
  var colore = d.colore || '#1e3a8a';
  var errori = [];

  window.addEventListener('error', function (e) {
    errori.push((e.message || 'errore') + (e.filename ? ' @ ' + e.filename + ':' + e.lineno : ''));
    if (errori.length > 5) errori.shift();
  });
  window.addEventListener('unhandledrejection', function (e) {
    errori.push('promise: ' + String(e.reason && (e.reason.message || e.reason)));
    if (errori.length > 5) errori.shift();
  });

  function tecnici() {
    return JSON.stringify({
      pagina: location.href,
      browser: navigator.userAgent,
      schermo: screen.width + 'x' + screen.height,
      finestra: innerWidth + 'x' + innerHeight,
      lingua: navigator.language,
      versione: d.versione || config.versione || '',
      utente_app: config.utente || '',
      errori: errori.join(' | ')
    });
  }

  var css = [
    ':host{all:initial}',
    '*{box-sizing:border-box;font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif}',
    '.btn{position:fixed;bottom:20px;' + (d.posizione === 'sinistra' ? 'left' : 'right') + ':20px;z-index:2147483000;',
    'background:' + colore + ';color:#fff;border:0;border-radius:22px;padding:11px 18px;font-size:14px;',
    'font-weight:600;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.18)}',
    '.velo{position:fixed;inset:0;z-index:2147483001;background:rgba(0,0,0,.35);display:flex;align-items:center;',
    'justify-content:center;padding:16px}',
    '.scheda{background:#fff;color:#1d1d1f;width:min(460px,100%);max-height:92vh;overflow:auto;border-radius:16px;',
    'padding:22px;box-shadow:0 20px 60px rgba(0,0,0,.25)}',
    'h2{margin:0 0 4px;font-size:18px}p{margin:0 0 14px;font-size:13px;color:#6e6e73}',
    'label{display:block;font-size:12px;font-weight:600;margin:10px 0 4px;color:#3a3a3c}',
    'input,select,textarea{width:100%;padding:9px 11px;border:1px solid #d2d2d7;border-radius:9px;font-size:14px}',
    'textarea{min-height:110px;resize:vertical}',
    '.riga{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}',
    '.sec{background:#f2f2f7;color:#1d1d1f;border:0;border-radius:9px;padding:8px 12px;font-size:13px;cursor:pointer}',
    '.pri{background:' + colore + ';color:#fff;border:0;border-radius:9px;padding:10px 16px;font-size:14px;',
    'font-weight:600;cursor:pointer}',
    '.pri:disabled{opacity:.5;cursor:default}',
    '.nota{font-size:12px;color:#6e6e73}.err{color:#c4271f;font-size:13px;margin-top:10px}',
    '.ok{color:#1f7a3a;font-size:15px;margin:10px 0}',
    '.esca{position:absolute;left:-9999px}',
    'img.anteprima{max-width:100%;margin-top:8px;border:1px solid #e5e5ea;border-radius:8px}'
  ].join('');

  var ospite = document.createElement('div');
  var ombra = ospite.attachShadow({mode: 'open'});
  ombra.innerHTML = '<style>' + css + '</style><button class="btn" type="button"></button>';
  ombra.querySelector('.btn').textContent = d.testo || 'Segnala un problema';
  (document.body ? Promise.resolve() : new Promise(function (r) { document.addEventListener('DOMContentLoaded', r); }))
    .then(function () { document.body.appendChild(ospite); });

  var catturato = null;

  function chiudi() { var v = ombra.querySelector('.velo'); if (v) v.remove(); catturato = null; }

  function cattura(anteprima, stato) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      stato.textContent = 'Il browser non permette la cattura: allega un file.';
      return;
    }
    navigator.mediaDevices.getDisplayMedia({video: true}).then(function (flusso) {
      var video = document.createElement('video');
      video.srcObject = flusso;
      video.muted = true;
      return video.play().then(function () {
        var tela = document.createElement('canvas');
        tela.width = video.videoWidth; tela.height = video.videoHeight;
        tela.getContext('2d').drawImage(video, 0, 0);
        flusso.getTracks().forEach(function (t) { t.stop(); });
        tela.toBlob(function (blob) {
          catturato = blob;
          anteprima.src = URL.createObjectURL(blob);
          anteprima.hidden = false;
          stato.textContent = 'Schermata catturata.';
        }, 'image/png');
      });
    }).catch(function () { stato.textContent = 'Cattura annullata.'; });
  }

  function apri() {
    if (ombra.querySelector('.velo')) return;
    var velo = document.createElement('div');
    velo.className = 'velo';
    velo.innerHTML =
      '<form class="scheda" novalidate>' +
      '<h2>Segnala un problema</h2><p>Raccontaci cosa succede: i dati tecnici della pagina li aggiungiamo noi.</p>' +
      '<label>Tipo</label><select name="tipo"><option value="bug">Qualcosa non funziona</option>' +
      '<option value="richiesta">Vorrei una modifica</option><option value="domanda">Ho una domanda</option></select>' +
      '<label>Oggetto</label><input name="oggetto" maxlength="200" required>' +
      '<label>Descrizione</label><textarea name="descrizione" maxlength="10000" ' +
      'placeholder="Cosa stavi facendo, cosa ti aspettavi, cosa è successo"></textarea>' +
      '<label>La tua email</label><input name="email" type="email" required>' +
      '<label>Nome</label><input name="nome" maxlength="200">' +
      '<input class="esca" name="sito_web" tabindex="-1" autocomplete="off" aria-hidden="true">' +
      '<label>Schermata</label><input name="screenshot" type="file" accept="image/*">' +
      '<div class="riga"><button class="sec" type="button" data-cattura>Cattura lo schermo</button>' +
      '<span class="nota" data-stato></span></div><img class="anteprima" hidden alt="">' +
      '<div class="err" data-errore hidden></div>' +
      '<div class="riga" style="justify-content:flex-end;margin-top:16px">' +
      '<button class="sec" type="button" data-chiudi>Annulla</button>' +
      '<button class="pri" type="submit">Invia</button></div></form>';
    ombra.appendChild(velo);
    var form = velo.querySelector('form');
    form.email.value = d.email || config.email || '';
    form.nome.value = d.nome || config.nome || '';
    velo.addEventListener('click', function (e) { if (e.target === velo) chiudi(); });
    velo.querySelector('[data-chiudi]').addEventListener('click', chiudi);
    velo.querySelector('[data-cattura]').addEventListener('click', function () {
      cattura(velo.querySelector('img.anteprima'), velo.querySelector('[data-stato]'));
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var errore = velo.querySelector('[data-errore]');
      errore.hidden = true;
      if (!form.oggetto.value.trim() || !form.email.value.trim()) {
        errore.textContent = 'Servono l\'oggetto e la tua email.'; errore.hidden = false; return;
      }
      var dati = new FormData(form);
      dati.set('tecnici', tecnici());
      if (catturato && !(form.screenshot.files && form.screenshot.files.length)) {
        dati.set('screenshot', catturato, 'schermata.png');
      }
      var invia = form.querySelector('.pri');
      invia.disabled = true;
      fetch(endpoint, {method: 'POST', body: dati, mode: 'cors'})
        .then(function (r) { return r.json().catch(function () { return {ok: false}; }); })
        .then(function (esito) {
          if (!esito.ok) throw new Error(esito.errore || 'invio non riuscito');
          form.innerHTML = '<h2>Grazie!</h2><p class="ok">Segnalazione ricevuta' +
            (esito.numero ? ': numero <strong>' + esito.numero + '</strong>' : '') +
            '. Ti risponderemo per email.</p><div class="riga" style="justify-content:flex-end">' +
            '<button class="pri" type="button" data-chiudi>Chiudi</button></div>';
          form.querySelector('[data-chiudi]').addEventListener('click', chiudi);
        })
        .catch(function (err) {
          errore.textContent = 'Non è stato possibile inviare: ' + err.message + '.';
          errore.hidden = false;
          invia.disabled = false;
        });
    });
    form.oggetto.focus();
  }

  ombra.querySelector('.btn').addEventListener('click', apri);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') chiudi(); });
})();
