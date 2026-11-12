# Note di rilascio

Ciò che chi aggiorna un'istanza deve sapere: cambi di comportamento, azioni da fare, migrazioni. Il dettaglio è nei
commit; qui solo ciò che si vede o che chiede un intervento.

## 2026-11-12

**Da sapere prima di aggiornare**

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
