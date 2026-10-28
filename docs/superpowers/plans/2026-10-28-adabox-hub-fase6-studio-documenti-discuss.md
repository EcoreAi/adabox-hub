# adabox-hub — piano di implementazione, fase 6: Studio, Documenti, Discuss

**Spec:** `docs/superpowers/specs/2026-10-28-adabox-hub-fase6-studio-documenti-discuss-design.md`.

**Regole per chi esegue:** come nei piani precedenti (test prima, suite verde con l'esito di pytest che decide il
commit, un commit per task con push, collaudo di ogni app nuova con `modulo collauda`).

### Task 1: Kernel — viste personalizzabili e voci della testata — fatto
- `core/viste/personalizza.py`: `registra`, `ATTRIBUTI`, `applica(vista, request)`; `ModelView.personalizzata`,
  `VistaBase.dispatch` usa la copia; `etichette` in `etichetta()` e nelle label del form.
- `prop_<nome>` singoli in `form_layout` (form e dettaglio) e in `list_display` (senza duplicare quelli `in_lista`).
- `hooks.voce_testata(template, order, permission)` e inclusione nella testata.
- Test con una funzione di personalizzazione di prova.

### Task 2: studio — personalizzazioni, editor, storico, campi nuovi, esporta/importa
### Task 3: documenti — cartelle, documenti, tag, pagina con albero, caricamento, anteprima, cestino, zip
### Task 4: documenti — condivisione pubblica, richieste, cartelle collegate ai modelli, sezione sui record
### Task 5: discuss — canali, iscrizioni, messaggi diretti, conversazione con polling, non letti
### Task 6: discuss — menzioni, posta in arrivo dal chatter, contatore in testata, email per i non letti
### Task 7: installazione di tutto, collaudo, README, verifica
