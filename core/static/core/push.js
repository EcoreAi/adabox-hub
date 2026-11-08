/* Notifiche push su questo dispositivo: [data-push] attiva o disattiva, [data-push-prova] manda una prova.
   Serve un indirizzo https (o localhost) e il consenso del browser; su iPhone l'app va prima aggiunta alla Home. */
(function () {
  'use strict';
  const bottoni = document.querySelectorAll('[data-push]');
  if (!bottoni.length) return;
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';
  const stato = document.querySelector('[data-push-stato]');
  const scrivi = (t) => { if (stato) stato.textContent = t; };
  const supportato = 'serviceWorker' in navigator && 'PushManager' in window && window.isSecureContext;
  const daBase64 = (s) => {
    const b = atob((s + '='.repeat((4 - (s.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(b, (c) => c.charCodeAt(0));
  };
  const manda = (iscrizione, disattiva) => fetch('/push/iscrivi/', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
    body: JSON.stringify({ ...iscrizione.toJSON(), disattiva: !!disattiva }),
  });
  const aggiorna = async () => {
    if (!supportato) {
      scrivi(window.isSecureContext ? 'Questo browser non riceve notifiche push.' : 'Le notifiche push richiedono un indirizzo https.');
      bottoni.forEach((b) => { b.disabled = true; });
      return null;
    }
    const reg = await navigator.serviceWorker.ready;
    const attuale = await reg.pushManager.getSubscription();
    bottoni.forEach((b) => { b.textContent = attuale ? 'Disattiva le notifiche su questo dispositivo' : 'Attiva le notifiche su questo dispositivo'; });
    scrivi(attuale ? 'Su questo dispositivo le notifiche sono attive.' : 'Su questo dispositivo le notifiche sono spente.');
    return attuale;
  };
  bottoni.forEach((b) => b.addEventListener('click', async () => {
    try {
      const attuale = await aggiorna();
      if (!supportato) return;
      const reg = await navigator.serviceWorker.ready;
      if (attuale) {
        await manda(attuale, true);
        await attuale.unsubscribe();
      } else {
        if ((await Notification.requestPermission()) !== 'granted') { scrivi('Il browser non ha dato il permesso.'); return; }
        const { chiave } = await (await fetch('/push/chiave/')).json();
        const nuova = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: daBase64(chiave) });
        await manda(nuova, false);
      }
      await aggiorna();
    } catch (e) { scrivi('Non è stato possibile: ' + e.message); }
  }));
  document.querySelectorAll('[data-push-prova]').forEach((b) => b.addEventListener('click', async () => {
    const r = await (await fetch('/push/prova/', { method: 'POST', headers: { 'X-CSRFToken': csrf() } })).json();
    scrivi(r.inviate ? 'Notifica di prova inviata.' : 'Nessun dispositivo ha accettato la notifica.');
  }));
  aggiorna();
})();
