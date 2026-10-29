# adabox-hub — piano AI-5: fiducia

**Spec:** `docs/superpowers/specs/2026-10-29-adabox-hub-modulo-ai-design.md` (fasi: proposta, sezione 6).
**Regole:** test prima, suite verde (SQLite e Postgres) che decide il commit, un commit per task con push,
collaudo del modulo `ai`.

**Esito atteso:** i dati personali non arrivano mai in chiaro a un modello cloud; sotto ogni risposta si vede da
dove vengono i dati e se qualche numero non è verificato; gli amministratori vedono il registro delle modifiche.

**Decisioni:**
- Servizio `adabox-pii` (mmBERT ONNX + regole, `POST /analyze`), raggiunto come gli embedding; URL nelle
  impostazioni (`ai.url_pii`). Senza URL la protezione è spenta (installazioni senza il servizio).
- Politica per anello della catena, nel gateway: i modelli non locali ricevono il testo mascherato, quelli locali
  in chiaro. Se il servizio non risponde quell'anello fallisce (errore `PII`, non si ripete) e si passa al
  successivo: nessun testo in chiaro verso il cloud.
- Il log degli eventi resta in chiaro (è nel nostro database). Si maschera a ogni chiamata, con una cache degli
  span per testo. Segnaposto stabili per conversazione (`Conversazione.segnaposto`): lo stesso valore ha sempre lo
  stesso segnaposto, e il prefisso mascherato resta identico per la cache del prompt.
- Uscita smascherata prima di arrivare all'utente e al log: testo in streaming (buffer da `[` a `]`), argomenti
  degli strumenti, blocchi finali. I blocchi nativi di Anthropic (ragionamento firmato) restano come li ha prodotti
  il modello, con l'indicazione `mascherato`: se la protezione cambia, quei blocchi non si rimandano.
- Esclusi di default DATE, TIME, AMOUNT, AGE, GENDER (servono ai calcoli, non identificano); elenco nelle
  impostazioni.
- Provenienza calcolata dal codice a fine turno, non dichiarata dal modello: strumenti usati, dati personali
  protetti, numeri della risposta assenti dai dati letti (guardia sui numeri), modello e costo.

### Task 1: protezione dei dati personali — fatto (commit unico con il task 2)
- `ai/protezione.py`: client del servizio con cache, vault dei segnaposto, mascheramento dei messaggi neutri,
  smascheramento di testo, argomenti e streaming; filtri di plausibilità (chiavi JSON, codici scambiati per nomi,
  numeri scambiati per CAP).
- Gateway: `esegui(catena, protezione=...)` applica la politica per anello; errore `PII` con messaggio chiaro.

### Task 2: provenienza e registro — fatto
- `Turno.provenienza`: strumenti, dati protetti, numeri non verificati, esito (`verificato`, `parziale`,
  `senza fonti`); riga di badge sotto la risposta.
- Vista «Registro modifiche» (proposte con utente, azienda, operazione, esito) per gli amministratori; dati
  protetti nei consumi.

### Task 3: installazione, collaudo, README, verifica dal vivo — fatto
- Versione `ai` 1.4.0, URL del servizio PII sul server, prova dal vivo.
