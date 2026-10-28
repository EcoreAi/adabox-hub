# adabox-hub — piano di implementazione, fase 5: il gestionale

**Spec:** `docs/superpowers/specs/2026-10-28-adabox-hub-fase5-gestionale-design.md`.

**Regole per chi esegue:** come nei piani precedenti (test prima, suite verde con l'esito di pytest che decide il
commit, un commit per task con push, collaudo di ogni app nuova con `modulo collauda`).

### Task 1: Kernel — righe dei documenti e hook demo — fatto
- `core.viste.Inline(model, fk, fields, titolo, extra)`, `ModelView.inlines`, `ModelView.totali(obj)` e
  `ModelView.dopo_righe(request, obj)`; form con formset (prefisso per inline, scelte filtrate per azienda, "Aggiungi
  riga" con `core/static/core/righe.js`), dettaglio con la tabella delle righe e i totali.
- `modulo_applica`: hook `demo(modulo)` chiamato solo con `--demo`.
- Test su un documento di prova.

### Task 2: fiscale — fatto
### Task 3: prodotti — fatto
### Task 4: vendite (preventivi, ordini, stampa, invio, segnale di conferma) — fatto
### Task 5: magazzino (movimenti, giacenze, consegne/DDT, ricevimenti, rettifiche, scorte) — fatto
### Task 6: acquisti (ordini fornitore, segnale di conferma, ricevimento) — fatto
### Task 7: fatturazione (dati fiscali, fatture, emissione, scadenze, incassi, note di credito) — fatto
### Task 8: fattura elettronica XML e registro IVA — fatto
### Task 9: installazione di tutto, collaudo, README, verifica
