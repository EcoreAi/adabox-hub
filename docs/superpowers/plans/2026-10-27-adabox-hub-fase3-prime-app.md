# adabox-hub — piano di implementazione, fase 3: le prime app

**Goal:** contatti, calendario, crm, helpdesk, progetti e timesheet come app in `addons/`, costruite solo con
`ModelView` e servizi del kernel, installabili con le dipendenze.

**Spec:** `docs/superpowers/specs/2026-10-27-adabox-hub-fase3-prime-app-design.md`.

**Regole per chi esegue:** come nei piani precedenti (test prima, suite verde con l'esito di pytest che decide il
commit, un commit per task con push). Ogni app: manifest con `depends`, gruppi Utente/Responsabile, icona SVG,
migrazione iniziale, `views.py`, fixture `data`/`demo`, `tests/`. `pytest.ini` forza tutte le app (`ADDONS_FORCE`) in
ordine di dipendenza.

---

### Task 0: Kernel — clienti esterni nel chatter — fatto
- `Messaggio.autore_email`; `ModelView.destinatari_esterni(obj)`; `chatter.email.notifica` include gli esterni
  (link al record solo per gli utenti); `entrata`: mittente esterno ammesso se tra i destinatari esterni del record
  (messaggio senza utente), registro `registra_gestore(funzione)` per le email non abbinate (il primo gestore che
  restituisce un record vince; esito `abbinata`).
- Test: notifica all'esterno, risposta dell'esterno, esterno non ammesso rifiutato, gestore che crea un record.

### Task 1: contatti — fatto
- Modelli, validatori fiscali (`addons/contatti/validatori.py`), vista con kanban per tipo, chatter, report,
  import/export, sezione "Persone" sul dettaglio delle aziende (hook nel `ready()`), dati iniziali (categorie) e demo.

### Task 2: calendario — fatto
- `Evento`, visibilità degli eventi privati, vista calendario, `.ics` (invito per email e download), pianificazione
  dei promemoria.

### Task 3: crm — fatto
- Fasi, etichette, motivi di perdita (dati iniziali), `Opportunita`, kanban per fase con regola della fase vinta,
  bottoni Vinta/Persa/Crea contatto, azione Assegna a me, parametro probabilità dalla fase.

### Task 4: helpdesk — fatto
- Team, fasi, `Ticket` con numero e SLA dai parametri, destinatari esterni, gestore delle email non abbinate,
  pianificazione SLA, bottoni Prendi in carico/Risolvi.

### Task 5: progetti
- Fasi, `Progetto`, `Compito`, permesso `vedi_tutti_progetti` e visibilità, sezione "Compiti" nel dettaglio del
  progetto.

### Task 6: timesheet
- `RigaOre` con validazioni e visibilità, sezioni "Ore" su progetto e compito, pagina `/timesheet/settimana/`.

### Task 7: installazione di tutte le app, documentazione, verifica
- Test end-to-end: DB vuoto, `modulo installa timesheet crm helpdesk calendario --demo --si` (le dipendenze si
  risolvono da sole), verifica dei dati, disinstallazione in ordine inverso.
- README (le app), installazione delle app nel DB di sviluppo, suite SQLite e Postgres, Docker.
