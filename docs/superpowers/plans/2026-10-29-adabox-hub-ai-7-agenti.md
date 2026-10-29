# adabox-hub — piano AI-7: agenti e qualità

**Spec:** `docs/superpowers/specs/2026-10-29-adabox-hub-modulo-ai-design.md` (fasi: proposta, sezione 6).
**Regole:** test prima, suite verde (SQLite e Postgres) che decide il commit, un commit per task con push,
collaudo del modulo `ai`.

**Esito atteso:** assistenti per app con istruzioni, strumenti e modello propri; esperti consultabili
dall'assistente principale; conversazioni lunghe che non sforano il contesto; regressioni bloccate in CI.

**Decisioni:**
- Nessuna scelta nuova nell'interfaccia della chat: la chat limitata a un'app usa l'assistente di quell'app, le
  altre l'assistente predefinito (proposta, sezione 2). Gruppi ammessi: chi non è nei gruppi ha il comportamento
  di base.
- Esperti = gli stessi assistenti, consultati con `chiedi_esperto` in una conversazione interna (non in
  cronologia, costi nei consumi). Un livello solo e sola lettura: le modifiche restano proposte dell'assistente
  principale, che l'utente vede e conferma. Il comportamento da esperto dipende dal compito del turno (`esperto`),
  non dal fatto che la conversazione sia interna.
- Compattazione: oltre una soglia la parte conclusa diventa un riassunto strutturato (Intento, Dati, Errori, In
  sospeso, Prossimo passo) con il profilo «riassunti». È un evento nuovo con l'ultimo evento riassunto: il log resta
  in sola aggiunta e la catena di strumenti del turno in corso non si spezza.
- Valutazione: domande d'oro con controlli dal codice (strumenti usati, testo, esito della provenienza). Con i
  copioni del modello finto girano nei test (CI); con il modello vero su richiesta, con il costo.

### Task 1: assistenti configurabili ed esperti — fatto
- Modello `Assistente` (app, predefinito, istruzioni, strumenti, profilo, gruppi, domande d'oro), vista
  «Assistenti»; motore con prompt, profilo e strumenti dell'assistente.
- Strumenti `elenco_esperti` e `chiedi_esperto` (visibili solo se ci sono assistenti).

### Task 2: compattazione — fatto
- `ai/motore/compattazione.py`, evento `riassunto`, storia per il modello dal riassunto più recente.

### Task 3: valutazione — fatto
- `ai/valutazione/` con `domande.json` (con copioni) e comando `manage.py ai_eval` (`--copioni`, `--assistente`,
  `--file`, `--utente`), uscita 1 se una domanda fallisce.

### Task 4: installazione, collaudo, README, verifica dal vivo — fatto
- Versione `ai` 1.6.0, prova sul server.
