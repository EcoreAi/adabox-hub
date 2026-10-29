# adabox-hub — piano: assistenza clienti per software house, fase 1

**Spec:** `docs/superpowers/specs/2026-10-29-adabox-hub-assistenza-software-design.md`.
**Regole:** test prima, suite verde (SQLite e Postgres) che decide il commit, un commit per task con push,
collaudo dei moduli toccati.

### Task 1: kernel — utenti esterni e impostazione della password — fatto
- `ProfiloUtente.esterno`; middleware: un utente esterno vede solo gli indirizzi del portale (e accesso, uscita,
  password), il resto rimanda al portale; la home lo manda al portale.
- Pagine per impostare la password da un link (invito, password dimenticata).

### Task 2: modulo `assistenza` — contratti SLA, supporto per progetto, instradamento — fatto
- Modelli `PoliticaSLA`, `Contratto`, `Supporto`, `DatiTicket`; calcolo delle scadenze (ore lavorative o 24 ore);
  prima risposta; instradamento per progetto e per cliente; viste di gestione; scheda «Assistenza» sul progetto.

### Task 3: widget di segnalazione — fatto
- Endpoint pubblico con CORS per dominio, limite di frequenza, campo esca, screenshot; `widget.js` da incollare;
  ticket instradato, risposta automatica al segnalante con il numero e il link al portale.

### Task 4: portale clienti — fatto
- Invito di un contatto (utente esterno legato al contatto); pagine: ticket (elenco, dettaglio con messaggi
  pubblici, risposta con allegati, nuovo ticket), progetti; nessuna nota interna visibile.

### Task 5: ticket ↔ compito di sviluppo — fatto
- Bottone «Crea compito di sviluppo»; alla chiusura del compito messaggio al cliente e ticket risolto.

### Task 6: installazione, collaudo, README, prova dal vivo — fatto
