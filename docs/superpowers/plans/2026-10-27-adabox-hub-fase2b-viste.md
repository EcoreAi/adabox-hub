# adabox-hub — piano di implementazione, fase 2b: le viste

**Goal:** dare a ogni `ModelView` le viste di Odoo oltre alla lista — raggruppamenti con totali, kanban con
trascinamento, calendario, grafico — e l'import/export CSV/XLSX, tutte dichiarate con attributi e con gli stessi
filtri, permessi e azienda della lista. `todo` 1.2.0 le usa.

**Spec:** `docs/superpowers/specs/2026-10-27-adabox-hub-fase2-kernel-completo-design.md` (sezione 2b).

**Architecture:** una vista generica per tipo in `core/viste/` (`kanban.py`, `calendario.py`, `grafico.py`,
`importa.py`, `esporta.py`), URL aggiunti da `ModelView.get_urls()` solo se la vista è dichiarata. Ricerca e filtri
restano in `filtri.applica` (stessi parametri `q`, `f_*`) e passano da una vista all'altra con il selettore nella
testata (`_selettore.html`). Nessuna libreria frontend nuova: drag & drop HTML5 nativo, grafici in SVG dal server.
Dipendenza nuova: `openpyxl`.

**Regole per chi esegue:** come nei piani precedenti (test prima, suite verde su SQLite, un commit per task con push,
`deploy/test-postgres.sh -q` alla fine).

---

### Task 1: Selettore di vista e raggruppamenti nella lista — fatto

- `ModelView`: `list_group_by` (campi con scelte, FK, booleani, date con `:mese`/`:anno`), `list_sum` (campi numerici).
- `?g=<campo>`: righe ordinate per gruppo, intestazione con etichetta, conteggio e somme dell'intero gruppo (una query
  `values().annotate()` sul queryset filtrato), gruppi chiudibili (`<details>`); paginazione invariata.
- Riga dei totali in fondo alla tabella per i campi in `list_sum` (sull'intero queryset filtrato).
- `_selettore.html` nella testata: Lista · Kanban · Calendario · Grafico (solo le viste dichiarate), conserva `q` e
  `f_*`; select "Raggruppa per" nei filtri della lista.
- Test: gruppi e conteggi, somme, raggruppamento per mese, gruppo vuoto (`—`), parametro non ammesso ignorato.

### Task 2: Kanban — fatto

- `kanban_group`, `kanban_fields`, `kanban_card` (template facoltativo), `kanban_limite` (50).
- `GET <slug>/kanban/`: colonne dalle scelte (in ordine) o dai record correlati (filtrati per azienda), conteggio,
  card con titolo (`__str__`) e campi resi come nel dettaglio; "altri N" con link alla lista filtrata.
- `POST <slug>/<pk>/sposta/` con `valore`: permesso `change`, valore validato (tra le colonne), salvataggio con
  tracciamento nel chatter; risposta 204 per HTMX, redirect altrimenti.
- `core/static/core/kanban.js`: drag & drop nativo (card `draggable`, colonne drop target), `fetch` POST con CSRF,
  ripristino della card se la risposta non è 2xx. Senza JS: select "Sposta in" nella card.
- Test: colonne e conteggi, filtri applicati, sposta (permessi, valore non valido 400, tracciamento), FK.

### Task 3: Calendario — fatto

- `calendar_date` (DateField o DateTimeField), `calendar_color` (campo con scelte, facoltativo).
- `GET <slug>/calendario/?mese=AAAA-MM` (griglia del mese, settimane da lunedì) e `?settimana=AAAA-MM-GG`; frecce
  avanti/indietro e "Oggi" con HTMX (`hx-get`, `hx-push-url`); eventi come pill colorate con link al dettaglio;
  click su un giorno vuoto → nuovo record con la data precompilata (`?<campo>=AAAA-MM-GG`, letto dal form come
  `initial`).
- Test: eventi nel giorno giusto (anche datetime in fuso Roma), mese e settimana, filtri, link al nuovo con la data.

### Task 4: Grafico — fatto

- `graph = {"tipi": [...], "misure": ["count", "sum:campo"], "per": ["campo", "campo:mese"]}`.
- `GET <slug>/grafico/?tipo=barre&misura=count&per=stato`: aggregazione nel DB sul queryset filtrato, etichette
  leggibili (scelte, FK, mesi in italiano), massimo 30 categorie (le altre in "Altro").
- `core/svg.py`: barre (verticali, assi e valori), linee (con punti), torta (spicchi con legenda); colori dalla
  palette del theme; `role="img"` e `<title>`; tabella dei dati sotto il grafico.
- Test: dati aggregati (count e sum), per mese, limite categorie, SVG valido (parse XML), parametri non ammessi → default.

### Task 5: Export — fatto

- Azione "Esporta" nella testata della lista: CSV (`;` e UTF-8 con BOM, come lo apre Excel in italiano) o XLSX
  (`openpyxl`, intestazioni in grassetto, larghezza colonne, date come date); righe = queryset filtrato o i `pk`
  selezionati; colonne = `export_fields` (default `list_display` senza `__str__`, più `id`).
- Oltre `EXPORT_SINCRONO_MAX` (5000) righe: lavoro nel worker; il file diventa un `Allegato` dell'utente stesso
  (record `User`), che solo lui può scaricare (regola aggiunta alla vista di download), e gli arriva il link per email.
- Permesso: `view`. Test: CSV e XLSX (rileggendo con `csv`/`openpyxl`), selezione, valori resi (scelte, FK, date),
  export grande nel worker.

### Task 6: Import

- `GET/POST <slug>/importa/`: carica CSV o XLSX → anteprima con mappatura colonne → campi (proposta per nome o
  etichetta, ignorare una colonna), opzione "aggiorna i record esistenti" se `import_key`.
- Validazione riga per riga con la `ModelForm` della vista (FK per nome o pk, scelte per valore o etichetta, date
  `gg/mm/aaaa` o ISO, booleani sì/no/1/0), **prova a secco** con l'elenco degli errori (riga, campo, messaggio), poi
  "Importa" in una transazione (tutto o niente). Oltre 1000 righe nel worker con esito nel chatter dell'utente.
- File temporaneo in `PRIVATE_MEDIA_ROOT/import/`, cancellato a fine import. Permessi: `add` (+ `change` per gli
  aggiornamenti). Test: mappatura proposta, prova a secco con errori, import riuscito, aggiornamento per chiave,
  tutto o niente, permessi.

### Task 7: `todo` 1.2.0, documentazione, verifica

- `todo` 1.2.0: `kanban_group = "stato"`, `calendar_date = "scadenza"`, `graph`, `list_group_by`, `import_key = "numero"`.
- README: le viste e l'import/export. Verifica: suite, Postgres, aggiornamento 1.1 → 1.2 nel test end-to-end,
  Docker.
