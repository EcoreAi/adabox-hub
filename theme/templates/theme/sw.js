/* Service worker dell'app installabile (PLT-16): una pagina «sei offline» quando la rete manca, stili e script in cache,
   notifiche push. Non mette in cache le pagine con i dati: ogni pagina viene sempre dal server.
   Fanno eccezione le pagine che un modulo dichiara apribili senza rete (hooks.pagina_senza_rete, es. uno scanner che
   tiene le foto nel telefono finché il server non le riceve): di quelle resta sul dispositivo l'ultima copia aperta
   con la rete, e si mostra quando la rete manca. */
const VERSIONE = 'adabox-1';
const PAGINE = 'adabox-pagine-1';                      // le ultime copie delle pagine senza rete, di chi usa questo dispositivo
const OFFLINE = '/offline/';
const STATICI = /\/static\//;
const SENZA_RETE = {{ senza_rete|safe }};              // {pagine: ['/iem/scansiona/'], statici: ['/static/iem/scansiona.js?v=…']}
const CAMBIA_PERSONA = /^\/accounts\/(login|logout)\//;

self.addEventListener('install', (e) => {
  // i file delle pagine senza rete entrano in cache subito; uno che manca non deve impedire l'installazione
  e.waitUntil(caches.open(VERSIONE)
    .then((c) => c.addAll([OFFLINE]).then(() => Promise.all(SENZA_RETE.statici.map((u) => c.add(u).catch(() => {})))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((chiavi) => Promise.all(chiavi.filter((k) => k !== VERSIONE && k !== PAGINE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const r = e.request;
  if (r.method !== 'GET') return;
  if (r.mode === 'navigate') {
    const percorso = new URL(r.url).pathname;
    // dal login e dal logout passa chi cambia persona: le copie delle pagine di prima non restano sul dispositivo
    if (CAMBIA_PERSONA.test(percorso)) e.waitUntil(caches.delete(PAGINE));
    if (SENZA_RETE.pagine.includes(percorso)) {        // dalla rete, tenendone una copia; senza rete, la copia
      e.respondWith(fetch(r).then((risposta) => {
        // solo la pagina vera: un reindirizzamento (al login, a sessione scaduta) o un errore non si salvano
        if (risposta.ok && !risposta.redirected && risposta.type === 'basic') {
          const copia = risposta.clone();
          e.waitUntil(caches.open(PAGINE).then((c) => c.put(percorso, copia)));
        }
        return risposta;
      }).catch(() => caches.open(PAGINE).then((c) => c.match(percorso)).then((salvata) => salvata || caches.match(OFFLINE))));
      return;
    }
    e.respondWith(fetch(r).catch(() => caches.match(OFFLINE)));   // le altre pagine: sempre dalla rete; senza rete la pagina offline
    return;
  }
  if (STATICI.test(new URL(r.url).pathname)) {         // stili, script, icone: dalla cache, aggiornati in background
    e.respondWith(caches.open(VERSIONE).then((c) => c.match(r).then((salvata) => {
      const rete = fetch(r).then((risposta) => { if (risposta.ok) c.put(r, risposta.clone()); return risposta; }).catch(() => salvata);
      return salvata || rete;
    })));
  }
});

self.addEventListener('push', (e) => {
  let dati = {};
  try { dati = e.data ? e.data.json() : {}; } catch (_) { dati = { titolo: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(dati.titolo || 'Notifica', {
    body: dati.testo || '', icon: '/icona-192.png', badge: '/icona-192.png', data: { url: dati.url || '/' },
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((finestre) => {
    for (const f of finestre) { if ('focus' in f) { f.navigate(url); return f.focus(); } }
    return self.clients.openWindow(url);
  }));
});
