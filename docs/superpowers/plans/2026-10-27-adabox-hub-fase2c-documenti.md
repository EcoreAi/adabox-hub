# adabox-hub — piano di implementazione, fase 2c: report PDF e campi personalizzati

**Goal:** stampe PDF dichiarate sulla `ModelView` (template Django con il layout del kernel, WeasyPrint) e campi
personalizzati per modello e azienda, aggiunti dal cliente senza migrazioni, presenti in form, dettaglio, lista,
filtri e API. `todo` 1.3.0 li usa.

**Spec:** `docs/superpowers/specs/2026-10-27-adabox-hub-fase2-kernel-completo-design.md` (sezione 2c).

**Regole per chi esegue:** come nei piani precedenti.

**Scostamenti decisi qui:**
1. Pango **non** si installa sull'host di sviluppo (server condiviso): i test che generano davvero il PDF girano
   nell'immagine Docker (`deploy/test-pdf.sh`); sull'host sono saltati e si verifica l'HTML del report.
2. La soglia per la stampa in background è sul numero di record (`REPORT_SINCRONO_MAX`, 20), non sulle pagine:
   le pagine si conoscono solo dopo aver generato il PDF.

---

### Task 1: Report PDF — fatto

- Dipendenza `weasyprint` (versione da `pip freeze`); `Dockerfile`: `libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core`.
- `ModelView.reports = [{"nome": "Scheda", "template": "todo/report/attivita.html"}]`.
- `core/report.py`: `html(vista, request, oggetti, indice)` (contesto: `oggetti`, `azienda` corrente con logo come
  `file://`, `vista`, `oggi`, `utente`), `pdf(html)` con import pigro di WeasyPrint → `ReportNonDisponibile` se manca
  la libreria; layout `core/report/base.html` (`@page` A4, intestazione con logo e dati dell'azienda, piè di pagina
  "pagina N di M", un record per pagina con `page-break`).
- URL `<slug>/<pk>/stampa/<int:indice>/` (bottone "Stampa" nel dettaglio, menu se più report) e
  `<slug>/stampa/<int:indice>/` POST con i `pk` (bottone nella barra delle azioni di massa). `?html=1` restituisce
  l'HTML (anteprima e test). Oltre `REPORT_SINCRONO_MAX` record: worker, allegato dell'utente, link per email.
  Senza WeasyPrint: 503 con un messaggio chiaro.
- Test: HTML del report (dati, azienda, un record per pagina), permessi (view; fuori azienda 404), indice non
  valido 404, stampa di massa, background, 503 senza libreria; PDF vero marcato `pdf` (saltato se manca Pango).

### Task 2: Campi personalizzati (Properties)

- `ProprietaMixin` (`proprieta = JSONField(default=dict, blank=True)`), `CampoPersonalizzato` (spec; unico per
  modello + nome + azienda; `modello` limitato ai modelli con `proprieta`).
- `core/proprieta.py`: `definizioni(modello, azienda)`, `campo_form(definizione)`, `in_json`/`da_json`, `testo`.
- `ModelView.get_form_class(request=None)`: aggiunge i campi `prop_<nome>` (iniziali da `instance.proprieta`);
  `save_model` li scrive in `obj.proprieta` (le chiavi non definite restano). Sezione "Altre informazioni" nel form e
  nel dettaglio, o dove indicato con `"@proprieta"` in `form_layout`.
- Lista: colonne `in_lista` (dopo `list_display`); filtri `filtrabile` (`scelta`, `booleano`, `utente`) con lookup
  JSON `proprieta__<nome>`; API: `proprieta` nell'output e nell'input (POST/PATCH).
- `/core/campi/`: `ModelView` del kernel per `CampoPersonalizzato` (permessi Django del modello), nel launcher.
- Test: form (obbligatorio, tipi), salvataggio senza perdere chiavi, per azienda, lista, filtro, API, dettaglio.

### Task 3: `todo` 1.3.0, Docker, documentazione, verifica

- `todo` 1.3.0: `Attivita` con `ProprietaMixin` (migrazione 0003), report "Scheda attività", `"@proprieta"` nel layout.
- `deploy/test-pdf.sh`: esegue i test marcati `pdf` nell'immagine Docker.
- README: report e campi personalizzati. Verifica: suite SQLite e Postgres, test PDF in Docker, aggiornamento
  end-to-end, `docker compose up` con stampa di una scheda.
