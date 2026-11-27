/* Il service worker del tema (theme/templates/theme/sw.js) eseguito senza browser: node sw_simulato.js <sw.js già reso>
   Lo lancia test_sw_senza_rete.py. Si simulano le cache, la rete, l'orologio e il browser che segue i reindirizzamenti
   (quelli del server gli arrivano opachi, come a una navigazione vera). Non è una prova sul telefono. */
const fs = require('fs');

const SORGENTE = fs.readFileSync(process.argv[2], 'utf8');
const SENZA_PAGINE = SORGENTE.replace(/const SENZA_RETE = \{.*?\};/, 'const SENZA_RETE = {"pagine": [], "statici": []};');
const ORIGINE = 'https://hub.example';
const COPIE = 'adabox-pagine-1';
const SCANNER = '/iem/scansiona/';
const AVVIO = '/tasca/?da=app';
const OFFLINE = 'pagina /offline/';

class Risposta {
  constructor(corpo = '', extra = {}) { Object.assign(this, { ok: true, status: 200, type: 'default', redirected: false }, extra, { corpo }); }
  static redirect(url, status) { return new Risposta('', { ok: false, status, location: url }); }
  clone() { return new Risposta(this.corpo, { ...this }); }
  async text() { return this.corpo; }
}

function ambiente(sorgente = SORGENTE) {
  const magazzini = new Map();                          // nome della cache -> Map(chiave -> risposta)
  // rete: "c'è", 'manca', 'lenta' (le richieste restano in `appese` finché non si fanno arrivare)
  // server[indirizzo]: {vaA: '/altra/'} reindirizza; {status: 502}; {corpo: '…'}; senza voce, la pagina di quell'indirizzo
  const stato = { rete: "c'è", server: {}, ascoltatori: {}, appese: [] };
  const orologio = { ora: 1000000, timer: new Map(), prossimo: 1 };
  const chiaveDi = (r) => { const u = new URL(typeof r === 'string' ? r : r.url, ORIGINE); return u.pathname + u.search; };

  const rispostaDelServer = (u) => {
    const s = stato.server[u.pathname + u.search] || stato.server[u.pathname] || {};
    if (s.vaA) return new Risposta('', { ok: false, status: 0, type: 'opaqueredirect', vaA: s.vaA });
    const status = s.status || (u.pathname.endsWith('manca.js') ? 404 : 200);
    return new Risposta(s.corpo || 'dal server ' + u.pathname, { ok: status < 400, status, type: 'basic', redirected: !!s.redirected });
  };
  const rete = (r) => {
    const u = new URL(r.url);
    if (stato.rete === 'manca') return Promise.reject(new TypeError('Failed to fetch'));
    if (stato.rete === 'lenta') return new Promise((risolvi) => stato.appese.push({ arriva: () => risolvi(rispostaDelServer(u)) }));
    return Promise.resolve(rispostaDelServer(u));
  };

  const apri = async (nome) => {
    if (!magazzini.has(nome)) magazzini.set(nome, new Map());
    const m = magazzini.get(nome);
    return {
      match: async (r) => { const x = m.get(chiaveDi(r)); return x && x.clone(); },
      put: async (r, risposta) => { m.set(chiaveDi(r), risposta); },
      delete: async (r) => m.delete(chiaveDi(r)),
      keys: async () => [...m.keys()].map((k) => ({ url: ORIGINE + k })),
      add: async (u) => { const x = await rete({ url: ORIGINE + u }); if (!x.ok) throw new Error('404'); m.set(u, x); },
      addAll: async (elenco) => { for (const u of elenco) m.set(u, new Risposta('pagina ' + u)); },
    };
  };
  const caches = {
    open: apri,
    has: async (nome) => magazzini.has(nome),
    keys: async () => [...magazzini.keys()],
    delete: async (nome) => magazzini.delete(nome),
    match: async (r) => { for (const m of magazzini.values()) { if (m.has(chiaveDi(r))) return m.get(chiaveDi(r)).clone(); } return undefined; },
  };

  const self = { addEventListener: (nome, f) => { stato.ascoltatori[nome] = f; }, skipWaiting: async () => {}, clients: { claim: async () => {} },
                 registration: {}, location: { origin: ORIGINE } };
  const metti = (f, ms) => { const id = orologio.prossimo; orologio.prossimo += 1; orologio.timer.set(id, { quando: orologio.ora + ms, f }); return id; };
  new Function('self', 'caches', 'fetch', 'URL', 'Response', 'setTimeout', 'clearTimeout', 'Date', sorgente)(
    self, caches, rete, URL, Risposta, metti, (id) => orologio.timer.delete(id), { now: () => orologio.ora });

  const respira = () => new Promise((fatto) => setImmediate(fatto));   // lascia finire le promesse in coda
  // il tempo passa: scattano i timer arrivati a scadenza
  const passa = async (ms) => {
    orologio.ora += ms;
    for (const [id, t] of [...orologio.timer]) { if (t.quando <= orologio.ora) { orologio.timer.delete(id); t.f(); } }
    await respira();
  };
  // un evento: la risposta data al browser e la fine di ciò che l'evento ha tenuto in vita (waitUntil)
  const evento = (nome, dati = {}) => {
    const attese = []; let risposta;
    stato.ascoltatori[nome]({ ...dati, waitUntil: (p) => attese.push(p), respondWith: (p) => { risposta = p; } });
    risposta = Promise.resolve(risposta);
    return { risposta, finito: risposta.then(() => Promise.all(attese)) };
  };
  const fatto = async (nome, dati) => { const e = evento(nome, dati); const r = await e.risposta; await e.finito; return r; };
  const apre = (indirizzo) => evento('fetch', { request: { method: 'GET', mode: 'navigate', url: ORIGINE + indirizzo } });
  // la risposta di un evento se è già stata data, altrimenti null
  const data = (e) => Promise.race([e.risposta.then((r) => r || null), respira().then(() => null)]);
  // il browser: apre un indirizzo e segue i reindirizzamenti, del server e del service worker; dove arriva e con che cosa
  const naviga = async (indirizzo) => {
    for (let salti = 0; salti < 5; salti += 1) {
      const e = apre(indirizzo);
      const risposta = await e.risposta; await e.finito;
      const prossimo = risposta && (risposta.vaA || (risposta.location && new URL(risposta.location).pathname));
      if (!prossimo) return { indirizzo, corpo: risposta && risposta.corpo };
      indirizzo = prossimo;
    }
    throw new Error('troppi reindirizzamenti');
  };
  const installa = async () => { await fatto('install'); await fatto('activate'); };
  return { stato, magazzini, caches, fatto, apre, data, passa, naviga, installa };
}

function atteso(condizione, dettagli) { if (!condizione) throw new Error(JSON.stringify(dettagli)); }
const copie = (a) => [...(a.magazzini.get(COPIE) || new Map()).keys()];

// un ambiente in cui l'avvio dell'app ha già portato una volta, con la rete, alla pagina senza rete
async function conAvvioImparato() {
  const a = ambiente();
  await a.installa();
  a.stato.server[AVVIO] = { vaA: SCANNER };
  const con = await a.naviga(AVVIO);
  atteso(con.indirizzo === SCANNER && con.corpo === 'dal server ' + SCANNER, { con });
  return a;
}

const scenari = {
  async 'la pagina dichiarata si apre senza rete con la copia dell\'ultima volta'() {
    const a = ambiente();
    await a.installa();
    const con = await a.naviga(SCANNER + '?da=app');
    a.stato.rete = 'manca';
    const senza = await a.naviga(SCANNER);
    atteso(con.corpo === 'dal server ' + SCANNER && senza.corpo === 'dal server ' + SCANNER, { con, senza });
  },
  async 'mai aperta con la rete: senza rete resta «Sei offline», come le altre pagine'() {
    const a = ambiente();
    await a.installa();
    a.stato.rete = 'manca';
    const mai = await a.naviga(SCANNER), altra = await a.naviga('/vendite/ordini/'), avvio = await a.naviga(AVVIO);
    atteso(mai.corpo === OFFLINE && altra.corpo === OFFLINE && avvio.corpo === OFFLINE && avvio.indirizzo === AVVIO, { mai, altra, avvio });
  },
  async 'le altre pagine non si salvano mai'() {
    const a = ambiente();
    await a.installa();
    await a.naviga('/vendite/ordini/');
    atteso(copie(a).length === 0, copie(a));
  },
  async 'un reindirizzamento al login o un errore non diventano la copia della pagina'() {
    const a = ambiente();
    await a.installa();
    for (const risposta of [{ vaA: '/accounts/login/' }, { redirected: true, corpo: 'login' }, { status: 500 }]) {
      a.stato.server[SCANNER] = risposta;
      await a.naviga(SCANNER);
    }
    a.stato.rete = 'manca';
    const senza = await a.naviga(SCANNER);
    atteso(senza.corpo === OFFLINE, senza);
  },
  async 'passando dal login o dal logout spariscono le copie, e dove portava l\'avvio'() {
    const a = await conAvvioImparato();
    atteso(copie(a).length === 2, copie(a));
    await a.naviga('/accounts/logout/');
    a.stato.rete = 'manca';
    const pagina = await a.naviga(SCANNER), avvio = await a.naviga(AVVIO);
    atteso(pagina.corpo === OFFLINE && avvio.corpo === OFFLINE && copie(a).length === 0, { pagina, avvio, copie: copie(a) });
  },
  async 'i file della pagina entrano in cache all\'installazione, e uno che manca non la blocca'() {
    const a = ambiente();
    await a.installa();
    const statici = a.magazzini.get('adabox-1');
    atteso(statici.has('/static/iem/scansiona.js?v=7') && !statici.has('/static/iem/manca.js?v=1') && statici.has('/offline/'), [...statici.keys()]);
  },
  async 'un aggiornamento tiene le copie e toglie quelle di pagine non più dichiarate'() {
    const a = await conAvvioImparato();
    await (await a.caches.open(COPIE)).put('/vecchia/', new Risposta('una pagina che non è più senza rete'));
    a.magazzini.set('adabox-0', new Map());
    await a.fatto('activate');
    atteso(copie(a).length === 2 && copie(a).includes(SCANNER) && !copie(a).includes('/vecchia/') && a.magazzini.has('adabox-1') && !a.magazzini.has('adabox-0'),
      { copie: copie(a), cache: [...a.magazzini.keys()] });
    a.stato.rete = 'manca';
    const avvio = await a.naviga(AVVIO);
    atteso(avvio.indirizzo === SCANNER, avvio);
  },
  async 'senza pagine dichiarate: nessuna copia, e «Sei offline» come sempre'() {
    const a = ambiente(SENZA_PAGINE);
    await (await a.caches.open(COPIE)).put(SCANNER, new Risposta('la copia di quando il modulo era acceso'));
    await a.installa();
    const con = await a.naviga('/vendite/ordini/');
    a.stato.rete = 'manca';
    const senza = await a.naviga('/vendite/ordini/'), pagina = await a.naviga(SCANNER);
    atteso(con.corpo === 'dal server /vendite/ordini/' && senza.corpo === OFFLINE && pagina.corpo === OFFLINE && !a.magazzini.has(COPIE), { con, senza, pagina });
  },

  async 'l\'app riaperta senza rete va alla copia della pagina a cui l\'avvio aveva portato'() {
    const a = await conAvvioImparato();
    a.stato.rete = 'manca';
    const senza = await a.naviga(AVVIO);
    atteso(senza.indirizzo === SCANNER && senza.corpo === 'dal server ' + SCANNER, senza);
  },
  async 'una scorciatoia già usata con la rete fa lo stesso; una che porta a un\'altra pagina no'() {
    const a = ambiente();
    await a.installa();
    a.stato.server['/tasca/?apri=iem:scansiona'] = { vaA: SCANNER };
    a.stato.server['/tasca/?apri=chat'] = { vaA: '/ai/chat/' };
    await a.naviga('/tasca/?apri=iem:scansiona'); await a.naviga('/tasca/?apri=chat');
    a.stato.rete = 'manca';
    const scanner = await a.naviga('/tasca/?apri=iem:scansiona'), chat = await a.naviga('/tasca/?apri=chat');
    atteso(scanner.indirizzo === SCANNER && scanner.corpo === 'dal server ' + SCANNER && chat.corpo === OFFLINE, { scanner, chat });
  },
  async 'se l\'avvio poi porta altrove, senza rete non si va più alla copia (che resta)'() {
    for (const ora of [{ vaA: '/parla/' }, {}]) {       // a un'altra pagina; oppure risponde «In tasca» stessa
      const a = await conAvvioImparato();
      a.stato.server[AVVIO] = ora;
      await a.naviga(AVVIO);
      a.stato.rete = 'manca';
      const avvio = await a.naviga(AVVIO), pagina = await a.naviga(SCANNER);
      atteso(avvio.corpo === OFFLINE && pagina.corpo === 'dal server ' + SCANNER, { ora, avvio, pagina });
    }
  },
  async 'un errore del server non fa dimenticare dove porta l\'avvio'() {
    const a = await conAvvioImparato();
    a.stato.server[AVVIO] = { status: 502 };
    await a.naviga(AVVIO);
    a.stato.rete = 'manca';
    const avvio = await a.naviga(AVVIO);
    atteso(avvio.indirizzo === SCANNER, avvio);
  },
  async 'con la rete lenta, dopo il tempo massimo si mostra la copia; la risposta arrivata tardi la aggiorna'() {
    const a = ambiente();
    await a.installa();
    await a.naviga(SCANNER);
    a.stato.rete = 'lenta'; a.stato.server[SCANNER] = { corpo: 'la pagina di adesso' };
    const e = a.apre(SCANNER);
    await a.passa(3999); const prima = await a.data(e);
    await a.passa(1); const dopo = await a.data(e);
    a.stato.appese.shift().arriva(); await e.finito;
    a.stato.rete = 'manca';
    const poi = await a.naviga(SCANNER);
    atteso(prima === null && dopo && dopo.corpo === 'dal server ' + SCANNER && poi.corpo === 'la pagina di adesso', { prima, dopo, poi });
  },
  async 'con la rete lenta l\'avvio dell\'app aspetta una volta sola'() {
    const a = await conAvvioImparato();
    a.stato.rete = 'lenta';
    const avvio = a.apre(AVVIO);
    await a.passa(3999); const prima = await a.data(avvio);
    await a.passa(1); const salto = await a.data(avvio);
    atteso(prima === null && salto && salto.status === 302 && salto.location === ORIGINE + SCANNER, { prima, salto });
    const pagina = a.apre(SCANNER);
    await a.passa(0); const copia = await a.data(pagina);
    atteso(copia && copia.corpo === 'dal server ' + SCANNER, { copia });
    // il reindirizzamento del server all'avvio arriva ora, a cose fatte: non va attribuito alla navigazione che segue
    a.stato.appese.shift().arriva(); await avvio.finito;
    a.stato.rete = "c'è";
    await a.naviga('/vendite/ordini/');
    a.stato.rete = 'manca';
    const ancora = await a.naviga(AVVIO);
    atteso(ancora.indirizzo === SCANNER, ancora);
  },
  async 'senza una copia la rete lenta si aspetta, per le pagine dichiarate e per le altre'() {
    const a = ambiente();
    await a.installa();
    a.stato.rete = 'lenta';
    for (const indirizzo of [SCANNER, '/vendite/ordini/', AVVIO]) {
      const e = a.apre(indirizzo);
      await a.passa(60000); const prima = await a.data(e);
      a.stato.appese.shift().arriva();
      const risposta = await e.risposta; await e.finito;
      atteso(prima === null && risposta.corpo === 'dal server ' + new URL(indirizzo, ORIGINE).pathname, { indirizzo, prima, risposta });
    }
  },
};

(async () => {
  let falliti = 0;
  for (const [nome, prova] of Object.entries(scenari)) {
    try { await prova(); console.log(`ok       ${nome}`); } catch (e) { falliti += 1; console.log(`FALLITO  ${nome}: ${e.message}`); }
  }
  process.exit(falliti ? 1 : 0);
})();
