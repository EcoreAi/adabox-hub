/* Service worker dell'app installabile (PLT-16): una pagina «sei offline» quando la rete manca, stili e script in cache,
   notifiche push. Non mette in cache le pagine con i dati: ogni pagina viene sempre dal server.
   Fanno eccezione le pagine che un modulo dichiara apribili senza rete (hooks.pagina_senza_rete, es. uno scanner che
   tiene le foto nel telefono finché il server non le riceve): di quelle resta sul dispositivo l'ultima copia aperta
   con la rete, e si mostra quando la rete manca o tarda troppo. Lo stesso per gli indirizzi che l'ultima volta hanno
   portato a una di quelle pagine (l'avvio dell'app, una scorciatoia): senza rete si va alla sua copia. */
const VERSIONE = 'adabox-1';
const PAGINE = '{{ cache_pagine }}';                   // le ultime copie delle pagine senza rete, di chi usa questo dispositivo
const OFFLINE = '/offline/';
const STATICI = /\/static\//;
const SENZA_RETE = {{ senza_rete|safe }};              // {pagine: ['/iem/scansiona/'], statici: ['/static/iem/scansiona.js?v=…']}
const CAMBIA_PERSONA = /^\/accounts\/(login|logout)\//;
const RICORDI = '/sw-porta-a/';                        // in PAGINE, accanto alle copie: indirizzo -> la pagina senza rete a cui ha portato l'ultima volta
const PORTA_A = RICORDI + '?da=';
const ATTESA = 4000;                                   // ms: se la copia c'è, la rete non si aspetta più di così
const DA_POCO = 10000;                                 // ms: per tanto, dopo un'attesa andata a vuoto, la copia si mostra subito
const SEGUE = 3000;                                    // ms: entro tanto il browser apre la pagina a cui il server ha reindirizzato
let reindirizzata = null;                              // {chiave, quando}: la navigazione che il server ha appena reindirizzato
let lenta = 0;                                         // quando la rete ha tardato troppo l'ultima volta

self.addEventListener('install', (e) => {
  // i file delle pagine senza rete entrano in cache subito; uno che manca non deve impedire l'installazione
  e.waitUntil(caches.open(VERSIONE)
    .then((c) => c.addAll([OFFLINE]).then(() => Promise.all(SENZA_RETE.statici.map((u) => c.add(u).catch(() => {})))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((chiavi) => Promise.all(chiavi.filter((k) => k !== VERSIONE && k !== PAGINE).map((k) => caches.delete(k))))
    // le copie di pagine che non sono più tra quelle senza rete (un modulo spento) non restano sul dispositivo
    .then(() => (SENZA_RETE.pagine.length ? caches.open(PAGINE).then((c) => c.keys().then((salvate) => Promise.all(salvate
      .filter((s) => { const p = new URL(s.url).pathname; return p !== RICORDI && !SENZA_RETE.pagine.includes(p); })
      .map((s) => c.delete(s))))) : caches.delete(PAGINE)))
    .then(() => self.clients.claim()));
});

// La copia sul dispositivo di una pagina senza rete, se c'è.
const copiaDi = (percorso) => (SENZA_RETE.pagine.includes(percorso) ? caches.open(PAGINE).then((c) => c.match(percorso)) : Promise.resolve());

// Per un indirizzo che l'ultima volta ha portato a una pagina senza rete di cui c'è la copia: il reindirizzamento a
// quella pagina (non la copia stessa: così l'indirizzo che si vede, e i link relativi, sono quelli della pagina).
const portaA = (chiave) => caches.open(PAGINE).then((c) => c.match(chiave)).then((r) => (r ? r.text() : ''))
  .then((percorso) => copiaDi(percorso).then((copia) => (copia ? Response.redirect(self.location.origin + percorso, 302) : undefined)));

/* Una pagina, quando almeno un modulo ne ha dichiarate di apribili senza rete. Sempre dalla rete; ma se sul dispositivo
   c'è la copia della pagina (o di quella a cui questo indirizzo ha portato l'ultima volta) la copia si mostra quando la
   rete manca, e anche quando tarda più di ATTESA: con il segnale debole la richiesta può restare appesa a lungo.
   Dove porta un indirizzo non si legge dalla risposta (il reindirizzamento di una navigazione arriva opaco): lo dice la
   navigazione che il browser fa subito dopo. */
function pagina(e) {
  const r = e.request, url = new URL(r.url), percorso = url.pathname;
  const chiave = PORTA_A + encodeURIComponent(percorso + url.search);
  const dichiarata = SENZA_RETE.pagine.includes(percorso);
  const da = reindirizzata && Date.now() - reindirizzata.quando < SEGUE ? reindirizzata.chiave : null;   // chi ha reindirizzato qui
  reindirizzata = null;
  let scaduta = false;                                 // si è risposto con la copia: la rete ha tardato troppo
  const rete = fetch(r);
  e.waitUntil(rete.then((risposta) => {
    if (risposta.type === 'opaqueredirect') {          // il server reindirizza (anche al login, a sessione scaduta)
      if (!scaduta) reindirizzata = { chiave: da || chiave, quando: Date.now() };
      return null;
    }
    // la copia si fa solo della pagina vera, non di un errore; arrivata tardi, aggiorna quella mostrata
    const copia = dichiarata && risposta.ok && !risposta.redirected && risposta.type === 'basic' ? risposta.clone() : null;
    const altrove = !dichiarata && risposta.ok;        // un'altra pagina: questo indirizzo non porta (più) a una pagina senza rete
    return caches.open(PAGINE).then((c) => Promise.all([
      copia && c.put(percorso, copia),
      copia && da && c.put(da, new Response(percorso)),
      altrove && da && c.delete(da),
      altrove && c.delete(chiave),
    ]));
  }).catch(() => {}));
  const ripiego = () => (dichiarata ? copiaDi(percorso) : portaA(chiave)).catch(() => undefined);
  e.respondWith(new Promise((risolvi) => {
    let data = false;
    const dai = (risposta) => { if (!data) { data = true; clearTimeout(timer); risolvi(risposta); } };
    // dopo un'attesa andata a vuoto non se ne fa un'altra subito: l'avvio dell'app che porta alla copia aspetta una volta sola
    const timer = setTimeout(() => ripiego().then((altra) => { if (altra && !data) { scaduta = true; lenta = Date.now(); dai(altra); } }),
      Date.now() - lenta < DA_POCO ? 0 : ATTESA);
    rete.then(dai, () => ripiego().then((altra) => dai(altra || caches.match(OFFLINE))));
  }));
}

self.addEventListener('fetch', (e) => {
  const r = e.request;
  if (r.method !== 'GET') return;
  if (r.mode === 'navigate') {
    // dal login e dal logout passa chi cambia persona: le copie delle pagine di prima non restano sul dispositivo
    if (CAMBIA_PERSONA.test(new URL(r.url).pathname)) { e.waitUntil(caches.delete(PAGINE)); reindirizzata = null; }
    else if (SENZA_RETE.pagine.length) { pagina(e); return; }
    e.respondWith(fetch(r).catch(() => caches.match(OFFLINE)));   // sempre dalla rete; senza rete la pagina offline
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
