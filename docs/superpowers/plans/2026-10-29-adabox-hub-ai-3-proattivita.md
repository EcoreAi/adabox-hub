# adabox-hub — piano AI-3: proattività

**Spec:** `docs/superpowers/specs/2026-10-29-adabox-hub-modulo-ai-design.md` (fasi: proposta, sezione 6).
**Regole:** test prima, suite verde (SQLite e Postgres) che decide il commit, un commit per task con push,
collaudo del modulo `ai`.

**Esito atteso:** "ogni lunedì alle 8 mandami gli ordini aperti sopra 5.000 €" diventa un'attività pianificata che
il worker esegue da sola, con i permessi di chi l'ha chiesta, e il cui risultato arriva in chat e in Discuss.

**Decisioni:**
- Ricorrenze proprie dell'assistente (ogni N ore, giorni della settimana, giorno del mese, prima degli eventi),
  non le pianificazioni del kernel, che conoscono solo intervalli fissi. Il kernel serve da orologio: una voce
  `cron` del modulo `ai` ogni minuto accoda il controllo delle scadute.
- Il risultato va sempre in una conversazione della chat dedicata alla pianificazione (grafici, tabelle e
  proposte funzionano come in chat). Discuss ed email sono consegne in più: `ai` non dipende da Discuss.
- In Discuss scrive un utente di sistema «Assistente» (non attivo, senza password) in un messaggio diretto:
  campanella, posta in arrivo ed email dei non letti seguono le regole di Discuss.
- Le scritture restano proposte: in un'esecuzione pianificata nessuno conferma, la proposta resta nella
  conversazione per 24 ore.

### Task 1: pianificazioni ed esecuzione — fatto (task 1-3 in un solo commit: codice intrecciato)
- Modello `Pianificata`: proprietario, azienda, nome, istruzioni, app, ricorrenza (`ore`, `giorni`, `mese`,
  `eventi`), ora, giorni della settimana, giorno del mese, ogni N ore, minuti prima degli eventi, consegna
  (Discuss, email), attiva, prossima ed ultima esecuzione, esito, errori di fila, conversazione.
- `ai/pianificate.py`: calcolo della prossima esecuzione, `esegui_scadute` (cron del manifest ogni minuto,
  una volta sola anche con più worker), esecuzione sincrona del turno con il compito `pianificate`, consegne,
  spegnimento dopo 3 errori di fila con avviso al proprietario.
- Profilo «Attività pianificate» con un limite di token adatto a un riepilogo (non 1024).

### Task 2: creazione dalla chat e gestione — fatto
- Strumenti `crea_pianificata` (proposta da confermare, con la frequenza scritta in chiaro), `elenco_pianificate`.
- Vista «Pianificate» (menu dell'assistente): le proprie pianificazioni (tutte per gli amministratori), form con
  i giorni della settimana a caselle, bottoni «Esegui ora», «Sospendi» / «Riattiva», link alla conversazione.
- Prompt e suggerimenti.

### Task 3: riepilogo del mattino e prima degli eventi — fatto
- «Attiva il riepilogo del mattino»: pianificazione pronta (lun-ven alle 8) con istruzioni standard.
- Ricorrenza `eventi`: per ogni evento del calendario dell'utente che inizia entro N minuti, un'esecuzione con
  i dati dell'evento (una sola per evento).

### Task 4: installazione, collaudo, README, verifica dal vivo — fatto
- Versione `ai` 1.2.0, collaudo, README, note di sessione, prova sul server.
