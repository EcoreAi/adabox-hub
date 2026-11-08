/* Service worker dell'app installabile (PLT-16): una pagina «sei offline» quando la rete manca, stili e script in cache,
   notifiche push. Non mette in cache le pagine con i dati: ogni pagina viene sempre dal server. */
const VERSIONE = 'adabox-1';
const OFFLINE = '/offline/';
const STATICI = /\/static\//;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSIONE).then((c) => c.addAll([OFFLINE])).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((chiavi) => Promise.all(chiavi.filter((k) => k !== VERSIONE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const r = e.request;
  if (r.method !== 'GET') return;
  if (r.mode === 'navigate') {                         // pagine: sempre dalla rete; senza rete la pagina offline
    e.respondWith(fetch(r).catch(() => caches.match(OFFLINE)));
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
