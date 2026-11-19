# Note di rilascio

Ciò che chi aggiorna un'istanza deve sapere: cambi di comportamento, azioni da fare, migrazioni. Il dettaglio è nei
commit; qui solo ciò che si vede o che chiede un intervento.

## 2026-11-19

- **AI 1.49.0 — «Parla con Ada» apre lei la conversazione** (una migrazione: `modulo aggiorna ai`).
  - La prima volta nella giornata Ada saluta e parte dall'agenda («Oggi hai 3 appuntamenti, il primo alle 10:00… Vuoi
    sapere cosa hai in agenda per oggi?»); tornando dopo un po' ricorda l'appuntamento che comincia entro un'ora, la
    modifica rimasta in attesa di conferma o propone di riprendere la conversazione di prima; tornando dopo pochi
    minuti non dice nulla. Ogni cosa una volta sola.
  - La frase è scritta appena si apre la pagina e Ada la dice **al primo tocco** (prima un browser non lascia suonare
    nulla), poi ascolta. La compone il server dai dati, non il modello.
  - Una conversazione a voce nuova sa di che cosa si è parlato a voce nella giornata («come dicevamo prima»).
  - Per le demo: `/ai/parla/?da_capo=1` fa ripartire il saluto del giorno. Dettagli in `docs/voce.md`.

## 2026-11-17

- **Cerca ovunque trova grafici, pagine e menu** — Kernel 1.4.0, Analisi 1.7.0, AI 1.47.0 (nessuna migrazione).
  - «grafico vendite quest'anno» trova i grafici salvati e le pagine di Analisi che l'utente vede, e le voci di menu,
    anche con i sinonimi delle misure («vendite» trova «Fatturato»). Se nessun grafico corrisponde, «Chiedi ad Ada»
    apre una chat nuova con la domanda già scritta.
  - Grafici salvati: l'icona ↻ accanto al titolo ricalcola subito, con l'ora dei dati («dati delle 12:35»); prima
    era solo nel menu ⋯. In chat grafici e tabelle si aggiornano lì dove sono (↻), senza aprire un'altra scheda.
- **Misure aziendali** — Kernel 1.3.0, AI 1.46.0, Analisi 1.6.0, Fatturazione 1.7.0, Vendite 1.9.0, Acquisti 1.6.0,
  Magazzino 1.15.0, Calendario 1.2.0, Connettore AI 1.1.0 (nessuna migrazione; i moduli con le misure chiedono il
  kernel 1.3).
  - Fatturato, fatture emesse, da incassare, scaduto, incassato, ordinato, preventivi aperti, acquistato, prodotti sotto
    scorta e appuntamenti hanno una definizione fissa. Ada, dashboard, Analisi e chat esterne danno lo stesso numero.
    **Cambia il numero che Ada dava per il fatturato**: prima dipendeva dal modello (ordini confermati, fatture con
    le bozze, totale IVA inclusa), ora è sempre l'imponibile delle fatture emesse meno le note di credito.
  - Sotto la risposta il chip «numeri usati» con la definizione e il link ai record.
  - I «primi 5 clienti» e simili funzionano anche negli strumenti generici (`ordina`, `primi`), senza i tentativi
    a vuoto di prima.
  - Le dashboard della Fatturazione e del Magazzino usano le stesse misure: un ruolo che non vede l'imponibile ora
    legge «non disponibile» invece del numero.
  - `ai_eval`: numero esatto delle misure, passi, tempi e `--modello`; 18 domande d'oro nuove sulle aree da demo.
  - Chat: con «Larga» e «Piena» la risposta, i grafici e le tabelle si allargano con la colonna (prima restavano
    stretti a sinistra); in «Piena» il testo si ferma a circa 120 battute, i grafici a 420 px di altezza. Ada non
    lascia più nel testo segnaposto come `![grafico](artifact:44)`.

## 2026-11-16

- **AI 1.45.0 — affidabilità delle previsioni e chat più larga** (nessuna migrazione).
  - Sotto ogni previsione il chip «Affidabilità: alta / media / bassa», calcolato dal codice da tre misure: quanta
    storia c'è (solida da 24 periodi), quanto è largo l'intervallo 10-90 %, e l'errore sugli ultimi periodi già noti
    (la stessa previsione rifatta senza di loro). La card dice i motivi; Ada lo dice anche a parole.
  - La colonna della chat si allarga: Normale (760 px), Larga (1100 px), Piena, oppure trascinando la maniglia sul
    bordo (doppio clic: normale; frecce da tastiera). Il browser ricorda la scelta; il testo resta a una larghezza
    comoda, tabelle e grafici usano lo spazio. Sul telefono non cambia nulla.
- **AI 1.44.0 — risposte più affidabili** (nessuna migrazione).
  - Guardia sui numeri più precisa: non segnala più date a parole («16 novembre»), misure («15 pollici», «500 W»),
    aliquote IVA, valori dichiarati approssimati vicini al dato vero, e conta come fonti i dati letti prima nella stessa
    chat. Sui turni veri: da 40 a 16 numeri segnalati; restano quelli davvero senza fonte (calcoli a mente, conoscenza
    generale).
  - La guardia «dati senza fonti» vale anche per le attività pianificate (oltre che a voce), e confronta i valori e non
    il testo («48.250,50» = 48250.5 nei dati).
  - Istruzioni di Ada: niente calcoli a mente su righe e totali; la conoscenza generale si dichiara («da verificare»);
    a voce, ciò che si può fare solo in chat si dice.
  - Domande d'oro da 7 a 19, con trappole (cliente e contratto inesistenti, fatturato di domani, eliminazione in blocco,
    conoscenza generale): `manage.py ai_eval`.
- **AI 1.43.0, Calendario 1.1.3 — ciò che non si tace.** Uno strumento può chiedere che una frase non manchi nella
  risposta (`da_ricordare`: testo e numero chiave): se il numero non compare, il motore la aggiunge. L'agenda la usa
  per gli appuntamenti già passati («Ne sono già passati 6 nel periodo: vuoi sentirli?»), che a voce il modello taceva
  anche con l'istruzione. L'agenda dà anche la sintesi dei numeri già scritta.
- **AI 1.42.0 — «Parla con Ada» più rapida** (nessuna migrazione). A voce 18 strumenti invece di 39 (meno token, meno
  attesa) e frasi d'attesa quando parte uno strumento. Consigliato nel profilo «Parla con Ada»: Mistral Medium 3.5.
- **AI 1.41.0 — «Parla con Ada» non legge dati inventati** (nessuna migrazione). Guardia «dati senza fonti» sulle
  risposte a voce: cifre che non vengono da nessuno strumento → la risposta si rifà una volta, poi un avviso a voce;
  sotto i sottotitoli le fonti o l'avviso. Cifre nel testo e parole solo nella voce; niente emoji lette. Nuova domanda
  d'oro sugli appuntamenti (`manage.py ai_eval`): un modello che risponde senza leggere il calendario non la passa.
- **Calendario 1.1.1** — l'agenda dell'assistente dice per ogni appuntamento se è passato, in corso o da venire.
- **AI 1.40.0 — «Parla con Ada» più veloce e più precisa** (migrazione `ai.0040`). Nuovo compito dei profili *Parla con
  Ada*: se c'è, i turni a voce usano il suo modello (es. uno veloce e regolare) e il suo tetto ai token; senza, resta la
  chat con «Automatico». Ada saluta per nome; Mistral riceve come parole da favorire il nome dell'assistente,
  dell'azienda e dell'utente.
- **AI 1.39.0 — trascrizione del parlato in cloud** (migrazione `ai.0039`). Nei servizi di «Voce» c'è il campo *uso*:
  con «Trascrizione del parlato» e tipo Mistral (Voxtral) o OVH (Whisper) la dettatura e «Parla con Ada» trascrivono in
  circa un secondo invece dei 6-8 del Whisper locale. Serve il consenso dell'azienda *Trascrizione del parlato con un
  fornitore cloud* (l'audio esce dal server); se il fornitore non risponde si usa il Whisper locale. I servizi già
  configurati restano di lettura.
- **AI 1.38.0 — «Parla con Ada»** (nessuna migrazione). Conversazione a voce a schermo intero (`/ai/parla/`): fine
  della frase automatica, risposte brevi, voce che parte mentre la risposta si scrive, riascolto dopo la risposta,
  interruzione con un tocco. **Sul telefono la chat si apre già così** quando la voce è accesa (dettatura e lettura);
  si spegne per azienda in Impostazioni → Assistente AI. Dettagli in `docs/voce.md`.

## 2026-11-15

- **Nuovo modulo SharePoint 1.0.0** (dipende da Documenti, migrazione `sharepoint.0001`). Una cartella dei Documenti
  allineata con una cartella di SharePoint, nel verso scelto, ogni 15 minuti; si prova senza credenziali con la
  SharePoint finta. Per un collegamento vero serve un'app in Microsoft Entra ID con `Sites.Selected` o
  `Sites.ReadWrite.All` (vedi README, «SharePoint»).

## 2026-11-12

**Da sapere prima di aggiornare**

- **AI 1.37.0 — «Fai dimenticare ad Ada»** (migrazione `ai.0038`). Nella scheda di un documento, per chi ha il permesso
  (gruppo «AI / Amministratore»): il documento esce dall'assistente e dalle chat di tutti gli utenti che lo avevano
  letto (le risposte di quei turni diventano una nota). Registro in Assistente AI → «Documenti dimenticati».
- **Kernel — file con lettere accentate.** Con nginx (X-Accel) un documento o un allegato con lettere accentate nel
  nome (es. «Che_cosa_è.pdf») dava 404 all'anteprima e al download: il percorso ora esce codificato. Serve
  l'immagine nuova.
- **AI — protezione dei dati personali.** Il nome dell'azienda, il marchio e le loro parole non si mascherano più,
  e un «nome utente» si maschera solo se è lo username di un utente: prima «che cos'è adabox?» arrivava al modello
  come «che cos'è [USERNAME_1]?» e Ada non cercava nei documenti.
- **AI 1.36.0 — conoscenza: pagine, stato dei documenti, citazioni verificate** (migrazione `ai.0037`).
  - La ricerca dell'assistente applica permessi e app della chat prima di tagliare la classifica: in «Chiedi alla
    wiki» o con molti record non visibili prima poteva rispondere «non trovo nulla» anche se la pagina c'era.
  - I PDF si indicizzano per pagina: al primo giro dopo l'aggiornamento i loro frammenti si rifanno (e si ricalcolano
    i vettori). La citazione apre l'anteprima alla pagina giusta.
  - Nella scheda di ogni documento la sezione «Per l'assistente» dice se Ada lo legge; le scansioni senza testo e i
    file protetti sono in Assistente AI → «Indice dei documenti».
  - Sotto le risposte che citano documenti, note o pagine compare «N su M citazioni verificate». Per le frasi dubbie
    parte una chiamata al profilo «Classificazione» (nei Consumi con il compito «verifica_citazioni»); si spegne
    nelle impostazioni.
  - Nuova impostazione, spenta: «Riassunto di ogni documento nell'indice». Accesa, ogni documento caricato o cambiato
    costa una chiamata al profilo «Riassunti» (compito «riassunto_documento»); senza protezione dei dati personali
    il testo va al modello così com'è.
- **Kernel 1.2.0.** I moduli possono dichiarare indirizzi alla radice dell'istanza (`urlpatterns_radice`), per i
  percorsi fissati da uno standard. Serve al nuovo modulo «Chat AI esterne», che sulle istanze con il kernel 1.1 non si
  installa: va aggiornata prima l'immagine (`deploy/flotta.py aggiorna`). Gli altri moduli non cambiano.
- **AI 1.35.0 — eliminando una chat i suoi costi restano.** I turni di una conversazione eliminata (a mano o dalla
  conservazione del modulo Privacy) non spariscono più dai Consumi: restano come righe di costo, senza più niente
  della conversazione (risposta, errore, passi, fonti). Prima cancellare le chat abbassava la spesa del mese, e con
  lei il tetto. Per lo stesso motivo le righe dei Consumi non si eliminano più, nemmeno dal Global Admin (migrazione
  `ai.0035`).
- **Discuss 1.13.1 — lavori di servizio.** Le risposte della chat del sito e dell'assistente del portale compaiono
  nei Consumi con il compito «servizio» invece di «riassunti»: chi filtra o raggruppa per compito le trova lì.
  Richiede AI 1.35.0.
- **Rivendita 1.5.0 — «canoni al mese».** Il numero della dashboard ora comprende le suite e il prezzo per utente:
  prima sommava solo piano e moduli in più, quindi può salire senza che sia cambiato nulla.

**Novità**

- **Rivendita 1.5.0 e AI 1.35.0 — le formule dell'assistente.** Nel piano, e se serve sull'istanza, si sceglie come
  si vende l'assistente: «chiave del cliente» (come finora), «inclusa nel canone» con una quota mensile per utente e
  per istanza, oppure «a consumo» con un ricarico e un tetto facoltativo. Il piano ha anche un prezzo per utente al
  mese. I termini arrivano all'istanza nella licenza firmata; chi non usa il portale li mette con
  `ai_licenza --formula … --quota-utente … --quota-istanza …`. Nessun cambiamento per chi resta su «chiave del cliente»
  (migrazioni `rivendita.0006`, `ai.0035`).
- **AI 1.35.0 — provider «fornito con il piano».** Il Global Admin segna così il provider che usa la chiave di chi
  vende. Il costo dei suoi modelli si conta a parte («Sul piano» nei Consumi) e vale per la quota: a quota finita quei
  modelli escono dalla catena fino al primo del mese, e la chat continua sui modelli con una chiave dell'azienda o
  locali, se ci sono. Provider, modelli e prezzi li cambia solo il Global Admin, e la chiave dell'azienda lì non vale.
  La chat avvisa dall'80% della quota; la pagina Licenza mostra formula, consumo del mese e consumo per utente, e
  segnala se la formula c'è ma nessun provider è segnato.
- **Rivendita 1.5.0 — Consumi AI.** Ogni ora le istanze con una formula diversa da «chiave del cliente» riferiscono al
  portale il riepilogo del mese in corso e del precedente (costi, turni, numero di persone: nessun nome). La pagina
  «Consumi AI» mostra, con «a consumo», l'importo da fatturare (costo sul piano × cambio × ricarico) e, con «inclusa»,
  il consumo rispetto alla quota. Il cambio dollaro → euro è un'impostazione del modulo: parte da 1,00 e va aggiornato
  a mano. I numeri li dichiara l'istanza: per quelle non ospitate il riscontro resta la fattura del fornitore.
- **AI 1.35.0 — OpenAI e Gemini tra i provider** (migrazione `ai.0036`). Due tipi nuovi accanto ad Anthropic e
  Mistral: basta la chiave, i modelli si scelgono dal catalogo del fornitore. I provider già configurati come
  «compatibile OpenAI» continuano a funzionare; passandoli al tipo nuovo, con OpenAI si usano anche i modelli che
  ragionano (rifiutano `max_tokens`) e con Gemini le chiamate agli strumenti dei modelli dalla serie 3 (rivogliono la
  firma del ragionamento, che prima andava persa: bastava il secondo passo per avere un errore 400). Provati con
  risposte simulate, non con i due servizi veri.
- **Chat AI esterne 1.0.0 (`connettore_ai`)**: adabox come connettore dentro Claude, ChatGPT, Gemini e Le Chat
  (migrazione `connettore_ai.0001`). Ogni persona collega la chat che usa già e da lì legge ciò che in adabox può
  vedere, con il suo abbonamento: sola lettura, permessi di ogni momento, registro delle chiamate, mascheramento dei
  dati personali se l'azienda lo accende. Spento finché un'azienda non lo accende in Impostazioni; serve un'istanza
  pubblica in https con `SITO_URL` corretto. Alla radice dell'istanza compaiono `/mcp` e due indirizzi sotto
  `/.well-known/`: il proxy deve passarli all'app. Provato con client simulati, non ancora con i quattro veri.

## 2026-11-11

**Da sapere prima di aggiornare**

- **Documenti 1.2.0 — gli spazi personali diventano privati.** L'impostazione «I responsabili dei documenti vedono gli
  spazi personali» passa a spenta di default: gli spazi personali li vede solo il proprietario, anche nell'elenco dei
  documenti dei responsabili e nella ricerca dell'assistente. Le aziende che l'avevano esplicitamente accesa non
  cambiano. Chi vuole il comportamento di prima la riaccende in Impostazioni → Documenti. Corretto anche un difetto:
  prima l'elenco dei documenti mostrava ai responsabili gli spazi personali anche con l'impostazione spenta.
- **Posta e calendario — invio dal chatter.** Le caselle collegate prima di questa versione non hanno il permesso di
  inviare: gli utenti che vogliono rispondere ai clienti dalla propria casella devono ricollegarla (la pagina lo
  dice). Fino ad allora i messaggi partono dall'indirizzo di sistema, come prima.

**Novità**

- **Connettori 1.4.0 — Odoo**, contatti e opportunità, con «ogni utente con la sua chiave»: ognuno collega il suo
  account da «I miei account esterni» e in adabox vede solo ciò che Odoo mostra a lui (migrazione `connettori.0005`).
  Le aziende si agganciano per partita IVA, anche negli altri connettori. Provato su un Odoo 19 vero.
  Con «le modifiche fatte in adabox tornano lì» contatti e opportunità salvati in adabox si scrivono in Odoo con la
  chiave di chi li salva (migrazione `connettori.0006`).
  Con «anche il calendario» arrivano anche gli appuntamenti di Odoo, in sola lettura (migrazione `connettori.0007`).
  Con «anche gli ordini di vendita» arrivano gli ordini di Odoo con righe e prodotti, in sola lettura: consegne e
  fatture restano a Odoo (migrazione `connettori.0008`). Nuovo nel kernel `core.esterni`: i documenti gestiti da un
  altro sistema non si modificano e non generano fatture né consegne.
- **Discuss 1.13.0 e Portale 1.2.0 — assistente nel portale clienti.** Nello sportello del sito si attiva «risponde
  anche nel portale clienti»: i clienti autenticati trovano la sezione «Assistente», che risponde con la conoscenza
  dello sportello, la guida pubblicata e il riepilogo dei loro documenti (gli stessi della home del portale). Non ha
  strumenti né accesso al database; quando non sa propone una richiesta di assistenza. Le domande sono visibili allo
  staff in Discuss → Domande dal portale (migrazione `discuss.0015`). Spento finché non si attiva.
- **AI 1.34.0 — ricerca mirata.** Si può chiedere all'assistente di cercare solo nei propri documenti o solo nella
  cartella dell'area di lavoro; le pagine della wiki sono indicizzate per intero, divise per sezioni.
- **Wiki 1.1.0 — «Chiedi alla wiki»** e domande senza risposta per i responsabili (migrazione `wiki.0002`).
- **Discuss 1.12.0 — la wiki come fonte dell'assistente del sito**: nello sportello si scelgono gli spazi pubblici
  (migrazione `discuss.0014`). Nessun cambiamento finché non se ne sceglie uno.
- **Connettori 1.3.0 — Salesforce e Zoho CRM** sullo stesso motore di HubSpot (migrazione `connettori.0004`). Provati
  solo contro sistemi simulati: prima di venderli, una prova con un'organizzazione vera (docs/collegamenti-esterni.md).
- **Nuovo modulo Posta e calendario**: casella e calendario Google o Microsoft per utente, da installare dove serve.
