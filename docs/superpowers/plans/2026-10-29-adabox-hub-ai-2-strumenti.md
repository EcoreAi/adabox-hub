# adabox-hub — piano AI-2: strumenti dalle app

**Spec:** `docs/superpowers/specs/2026-10-29-adabox-hub-modulo-ai-design.md` (fasi: proposta, sezione 6).
**Regole:** test prima, suite verde (SQLite e Postgres) che decide il commit, un commit per task con push,
collaudo del modulo `ai`.

**Esito atteso:** "quanti ordini aperti ha Rossi? crea un'attività per domani" — l'assistente legge i dati delle app
con i permessi di chi chiede, propone le modifiche e le esegue solo dopo il clic su «Conferma».

**Decisione:** strumenti generici con la vista come argomento (`cerca_record(vista="vendite.ordini", …)`), non
sette strumenti per ogni vista. Con 20 app sarebbero centinaia di definizioni: troppi token in ogni richiesta e un
prefisso diverso per ogni utente. Il modello scopre le viste con `elenco_viste` e `descrivi_vista`; il codice
valida vista, campi, filtri e permessi a ogni chiamata.

### Task 1: letture — viste, ricerca, dettaglio, aggregazioni
- `ai/strumenti/richiesta.py`: richiesta finta (utente, azienda, messaggi raccolti) per usare le `ModelView` come
  dal browser, con le personalizzazioni di Studio.
- `ai/strumenti/viste.py`: `elenco_viste`, `descrivi_vista`, `cerca_record`, `leggi_record`, `aggrega_record`.
  - solo viste che l'utente può vedere, mai quelle del modulo `ai`; nelle chat limitate a un'app, solo quell'app;
  - filtri su campi veri del modello (anche un salto su una relazione), operatori ammessi (`gte`, `lte`, `in`,
    `icontains`, `isnull`…), campi sensibili (password, chiavi, token, segreti) esclusi ovunque;
  - risultati con i valori leggibili delle relazioni e delle scelte e il link al record.
- Markdown della chat: link relativi (`/vendite/ordini/3/`) ammessi.
- Prompt di sistema (sempre byte-stabile) con il modo d'uso degli strumenti.

### Task 2: scritture con conferma
- Modello `Proposta`: operazione salvata (strumento e argomenti), anteprima, rischio, stato (in attesa,
  eseguita, annullata, fallita, scaduta), esito, impronta del record al momento della proposta.
- Registro: uno strumento non di lettura non si esegue. Si chiama la sua `anteprima` (valida e descrive) e si
  salva una proposta; il modello riceve «in attesa di conferma».
- Strumenti `crea_record` (anche con le righe del documento), `modifica_record`, `elimina_record`,
  `esegui_bottone`, `esegui_azione`, `pianifica_attivita`. Rischio dei bottoni dall'attributo `rischio` del
  metodo (default `scrittura`); `irreversibile` sui bottoni che emettono, inviano o cancellano.
- Interfaccia: scheda sotto la risposta con anteprima e «Conferma» / «Annulla»; per le irreversibili un
  riepilogo in evidenza e una casella da spuntare. Alla conferma si esegue l'operazione salvata, non argomenti
  nuovi, con i permessi ricontrollati; si rifiuta se la proposta è scaduta o il record è cambiato nel frattempo.
- Nota nel chatter del record («tramite l'assistente»). L'esito arriva al modello nel `<contesto>` del messaggio
  successivo: il log resta in sola aggiunta.

### Task 3: grafici (ChartSpec) e artifact tabella
- Modello `Artifact` (grafico o tabella): spec JSON scritta dal modello, dati calcolati dal codice, istantanea al
  momento della risposta.
- Strumenti `grafico` (barre, linee, torta, disegnati in SVG dal kernel) e `tabella` (righe di una ricerca).
- Grafici e tabelle sotto la risposta; si salvano nei pannelli «Grafici salvati» e «Artifact salvati»; la
  pagina dell'artifact ricalcola con i dati di oggi ed esporta in CSV.

### Task 4: strumenti dichiarati dalle app (chiave `"ai"` nel manifest)
- `"ai": "<app>.ai"` nel manifest: il modulo indicato registra i suoi `Strumento` (con `app` = slug).
- Esempi: `calendario.agenda` (eventi di un periodo, lettura).

### Task 5: installazione, collaudo, README, verifica dal vivo
- Versione `ai` 1.1.0 con migrazioni, collaudo, README, note di sessione; prova sul server con il modello finto.
