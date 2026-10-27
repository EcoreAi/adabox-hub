# adabox-hub — fase 2: il kernel completo

Data: 2026-10-27
Stato: **bozza da approvare** (decisioni aperte nella sezione finale, con la raccomandazione)
Precede: `2026-10-27-adabox-hub-fase1-kernel-design.md` (fase 1, completata: vedi `docs/sessioni/2026-10-27-fase1-kernel.md`)

## Scopo

La fase 1 ha dato il kernel minimo: moduli installabili, `ModelView` con lista, form,
dettaglio, azioni e API, multi-azienda. Mancano i servizi trasversali che in Odoo ogni app
dà per scontati e che le app della fase 3 (contatti, crm, helpdesk, progetti) useranno dal
primo giorno: lo storico e i messaggi sul record, le attività pianificate, gli allegati, le
numerazioni, le viste kanban, calendario e grafico, le stampe PDF, i lavori in background, le
impostazioni e l'import/export.

Metro di riuscita: con la fase 2 pronta, `todo` ottiene chatter, attività, allegati, kanban
per stato, calendario per scadenza, grafico, stampa PDF, un lavoro pianificato, un parametro,
import ed export e un campo personalizzato **dichiarando attributi**, senza scrivere viste né
template. Le app della fase 3 non scrivono infrastruttura.

Riferimento funzionale: Odoo 19 Community (mail.thread, mail.activity, ir.attachment,
ir.sequence, ir.cron, res.config.settings, viste kanban/calendar/graph, report QWeb,
Properties). Come in fase 1 si riproducono funzionalità e flussi, **non** codice, template,
CSS o testi.

## Suddivisione e ordine

La fase è grande: si divide in tre piani, ognuno chiuso e rilasciabile da solo.

| Piano | Contenuto | Perché in quest'ordine |
|---|---|---|
| **2a — servizi** | worker e cron, parametri e impostazioni, sequenze, allegati, chatter (messaggi, note, follower, tracciamento, email in uscita), attività pianificate | tutto il resto ne dipende: l'email del chatter e i report pesanti girano nel worker |
| **2b — viste** | raggruppamenti nella lista, kanban, calendario, grafico, import ed export | si appoggiano a `ModelView` e ai filtri della fase 1 |
| **2c — documenti e personalizzazione** | report PDF, campi personalizzati (Properties) | i report usano worker e allegati; le Properties toccano form, lista, filtri e API |

Ogni piano porta `todo` avanti con la sua parte e chiude con un test di installazione vergine.

## 2a — Servizi

### Worker e lavori pianificati

Coda di lavori **nel database**, senza servizi in più (niente Redis, niente broker):

- **`Lavoro`**: `funzione` (percorso Python puntato), `argomenti` (JSON), `stato`
  (`in_coda`, `in_corso`, `fatto`, `fallito`), `tentativi`, `max_tentativi`, `esegui_dopo`,
  `iniziato`, `finito`, `errore`, `azienda` (facoltativa), `utente` (facoltativo).
- **API**: `core.lavori.accoda("todo.lavori.invia_promemoria", pk=3, ritardo=60)`; la funzione
  riceve gli argomenti JSON, non oggetti. Ritenta con backoff (1, 5, 30 minuti) fino a
  `max_tentativi`, poi `fallito` con lo stack.
- **Worker**: `manage.py worker` in un ciclo: prende un lavoro con
  `select_for_update(skip_locked=True)` su Postgres (su SQLite, solo sviluppo, un worker alla
  volta), lo esegue in una transazione propria, dorme 2 s se la coda è vuota. Si ferma pulito
  su SIGTERM. Più worker in parallelo su Postgres senza coordinamento.
- **`Pianificazione`** (cron): dichiarata nel manifest, sincronizzata all'installazione:
  ```python
  "cron": [{"nome": "Promemoria scadenze", "funzione": "todo.lavori.promemoria", "ogni": "1d", "alle": "07:00"}],
  ```
  `ogni` in `m|h|d` (15m, 1h, 1d), `alle` facoltativo per i giornalieri. Il worker, a ogni giro,
  accoda le pianificazioni scadute e ne aggiorna `prossima_esecuzione` nella stessa
  transazione (una sola esecuzione anche con più worker). Attivabili/disattivabili dall'admin.
- **Sviluppo e test**: `LAVORI_SINCRONI=True` (default con `DEBUG` e nei test) esegue
  `accoda` subito, nello stesso processo; il worker serve solo per provare la coda vera.
- **Deploy**: servizio `worker` nel compose, stessa immagine, `python manage.py worker`.
  La ricarica dopo un'installazione lo riavvia (SIGTERM, `restart: unless-stopped`).
- **Pagina** `/core/lavori/` (superuser): `ModelView` in sola lettura con filtro per stato e
  bottone "Riprova".

### Parametri e impostazioni

- **`Parametro`**: `chiave` (`<modulo>.<nome>`), `valore` (JSON), `azienda` (null = globale).
  `core.parametri.leggi("todo.giorni_preavviso", azienda=None)` cerca prima per azienda, poi
  globale, poi il default del manifest. Cache per richiesta.
- **Manifest**:
  ```python
  "settings": [
      {"chiave": "giorni_preavviso", "label": "Giorni di preavviso", "tipo": "intero", "default": 2,
       "per_azienda": True, "help": "Quanti giorni prima della scadenza mandare il promemoria"},
  ],
  ```
  Tipi: `testo`, `intero`, `decimale`, `booleano`, `scelta` (con `scelte`), `data`.
- **Pagina** `/impostazioni/` (permesso `core.change_parametro`): una sezione per modulo
  installato con `settings`, form generata, salvataggio per l'azienda corrente o globale.
  `settings_url` del manifest (fase 1) resta per le pagine scritte a mano e diventa di default
  l'ancora del modulo in `/impostazioni/`.

### Sequenze

- **`Sequenza`**: `codice` (`todo.attivita`), `azienda`, `formato` (`"ATT/{anno}/{numero:05d}"`),
  `prossimo`, `azzera` (`mai`, `anno`). `core.sequenze.prossimo("todo.attivita", azienda)` con
  `select_for_update`: niente buchi né duplicati sotto concorrenza (su Postgres).
- Dichiarate nel manifest (`"sequences": [{"codice": ..., "formato": ...}]`), create
  all'installazione per ogni azienda e alla creazione di una nuova azienda.
- `ModelView.sequence_field = ("numero", "todo.attivita")` assegna il numero alla creazione.

### Allegati

- **`Allegato`** generico (`content_type`, `object_id`): `file`, `nome`, `mime`, `dimensione`,
  `caricato_da`, `creato`, `azienda`. I file stanno in `PRIVATE_MEDIA_ROOT`
  (`private/`, **non** servito da nginx): si scaricano da `/allegati/<pk>/` solo se l'utente può
  vedere il record a cui l'allegato appartiene (il controllo lo fa la `ModelView` del modello).
  In produzione il download passa a nginx con `X-Accel-Redirect` verso una location `internal`.
- Limiti: `ALLEGATI_MAX_MB` (default 20), estensioni vietate (eseguibili), nome ripulito.
- Mostrati nel pannello del chatter e utilizzabili dai messaggi.

### Chatter

Il pannello a destra (o sotto, su mobile) del dettaglio, come in Odoo, attivato con
`ModelView.chatter = True`:

- **`Messaggio`** generico: `tipo` (`nota` interna, `messaggio` ai follower, `tracciamento`
  automatico, `sistema`), `autore`, `corpo` (testo con a capo e link; niente HTML libero),
  `allegati` (M2M), `creato`. Ordinati dal più recente; caricamento a pagine con HTMX.
- **Tracciamento**: `ModelView.tracked_fields = ["stato", "assegnatario", "scadenza"]`: a ogni
  salvataggio dalla `ModelView` o dall'API, un messaggio `tracciamento` con
  "Stato: Aperta → Fatta". Le modifiche fatte da codice si tracciano con
  `core.chatter.traccia(obj, vecchi_valori)` (niente segnali globali: troppo costosi e
  imprevedibili).
- **Follower**: `Follower(content_type, object_id, utente)`. L'autore di un record e chi scrive
  un messaggio diventano follower; si segue/smette dal pannello. Un `messaggio` (non una nota)
  arriva per email ai follower tranne l'autore.
- **Email in uscita**: accodata nel worker (`core.chatter.invia_notifica`), template testo +
  HTML con il theme, `EMAIL_URL` della fase 1. Oggetto `[<brand>] <record>`, link al dettaglio.
  **Email in entrata (rispondere alla mail): fuori da questa fase.**
- Il pannello è una sezione di dettaglio registrata dal kernel (meccanismo `hooks` della fase 1),
  quindi anche i moduli possono aggiungerne accanto.

### Attività pianificate

Le "attività" di Odoo (mail.activity): cose da fare **su un record**, con scadenza e assegnatario.

- **`AttivitaPianificata`** generica: `tipo` (`TipoAttivita`: nome, icona, giorni di default;
  dati iniziali "Chiamata", "Email", "Riunione", "Da fare"), `riepilogo`, `nota`, `scadenza`,
  `assegnatario`, `creato_da`, `azienda`. Quando si segna fatta diventa un messaggio nel chatter
  ("Chiamata fatta: …") e la riga si cancella, come in Odoo.
- Nel pannello del chatter: elenco con colore per scadenza (scaduta, oggi, futura), "Pianifica",
  "Fatta", "Modifica".
- **"Le mie attività"** nel launcher e in `/attivita/`: tutte quelle assegnate all'utente,
  raggruppate per scadenza, con link al record. Contatore nell'header (via context processor,
  una query).
- Promemoria giornaliero per email delle attività in scadenza: una `Pianificazione` del kernel.
- Il nome `AttivitaPianificata` evita la confusione con `todo.Attivita`; in fase 3 `todo` può
  passare a usare queste (decisione già presa in fase 1).

## 2b — Viste

Tutte dichiarate sulla `ModelView`, con un selettore di vista nella testata della lista
(Lista · Kanban · Calendario · Grafico) che conserva ricerca e filtri.

### Raggruppamenti nella lista

- `?g=<campo>` (campi in `list_group_by`): righe raggruppate con intestazione, conteggio e
  somme dei campi in `list_sum`; gruppi chiudibili. Un livello solo in questa fase.
- La paginazione resta sulle righe; le intestazioni di gruppo hanno i totali dell'intero gruppo
  (una query aggregata), non della pagina.

### Kanban

- `kanban_group = "stato"` (campo con scelte o FK), `kanban_fields = ["titolo", "scadenza",
  "assegnatario"]`, `kanban_card` facoltativo (template della card).
- Colonne = valori del campo (scelte in ordine; per le FK i record del modello correlato filtrati
  per azienda); conteggio per colonna; 50 card per colonna con "altri…".
- **Trascinamento** di una card tra colonne: `POST <slug>/<pk>/sposta/` con il nuovo valore,
  stessi permessi e tracciamento di una modifica. Drag & drop HTML5 nativo con un piccolo
  `core/static/core/kanban.js`: **nessuna libreria** in più.

### Calendario

- `calendar_date = "scadenza"` (date o datetime), `calendar_end` facoltativo,
  `calendar_color` facoltativo (campo con scelte).
- Vista mese e settimana resa dal server (griglia HTML), navigazione con HTMX, click su un
  giorno = nuovo record con la data precompilata. Niente librerie JS di calendario.

### Grafico

- `graph = {"tipi": ["barre", "linee", "torta"], "misure": ["count", "sum:ore"], "per": ["stato", "scadenza:mese"]}`.
- Aggregazione nel DB (`values().annotate()`), stessi filtri della lista.
- Disegno in **SVG generato dal server** (barre, linee, torta, con i colori del theme), più la
  tabella dei dati sotto il grafico (accessibilità ed export).

### Import ed export

- **Export** CSV e XLSX dalla lista (righe filtrate o selezionate, colonne di `list_display` o
  scelte dall'utente), con `openpyxl`; oltre 5000 righe si genera nel worker e si scarica da
  un link (allegato all'utente).
- **Import** CSV e XLSX: caricamento, anteprima con mappatura colonne → campi (proposta per
  nome/label), validazione riga per riga con la `ModelForm` della vista, **prova a secco**
  con l'elenco degli errori, poi conferma. Aggiornamento di record esistenti per un campo chiave
  scelto (`import_key = "codice"`). Nel worker oltre 1000 righe.
- Permessi: export = `view`, import = `add` (+ `change` per gli aggiornamenti).

## 2c — Documenti e personalizzazione

### Report PDF

- Dichiarati sulla vista: `reports = [{"nome": "Scheda attività", "template": "todo/report/attivita.html"}]`;
  bottone "Stampa" nel dettaglio e azione di massa nella lista (un PDF con più pagine).
- Template Django con un layout di stampa del kernel (`core/report/base.html`: intestazione con
  logo e dati dell'azienda corrente, piè di pagina con numero di pagina).
- Generazione con **WeasyPrint** (HTML+CSS → PDF, licenza BSD). Richiede Pango: va
  nell'immagine Docker (`libpango-1.0-0 libpangoft2-1.0-0`) e sull'host di sviluppo; i test che
  generano davvero il PDF si saltano se la libreria manca.
- Sotto le 20 pagine il PDF si genera nella richiesta; oltre, nel worker, e si salva come
  allegato del record (con messaggio nel chatter).

### Campi personalizzati (Properties)

Campi aggiunti dal cliente senza migrazioni:

- **`CampoPersonalizzato`**: `modello` (content type), `nome` (slug), `label`, `tipo`
  (`testo`, `intero`, `decimale`, `booleano`, `data`, `scelta`, `utente`), `scelte`,
  `obbligatorio`, `in_lista`, `filtrabile`, `ordine`, `azienda` (null = tutte).
- I modelli che li accettano usano **`ProprietaMixin`** (`proprieta = JSONField(default=dict)`).
  La `ModelView` aggiunge i campi alla form (sezione "Altro" o dove indicato da
  `form_layout` con `"@proprieta"`), al dettaglio, alla lista (`in_lista`), ai filtri
  (`filtrabile`, con lookup JSON su Postgres) e all'API (oggetto `proprieta`).
- Gestione da `/impostazioni/campi/` (permesso `core.change_campopersonalizzato`).
- Diverso da Odoo, dove le Properties sono definite su un record "padre" (es. il progetto):
  qui sono per modello (e azienda). Il caso "padre" si valuta in fase 3 con i progetti.

## Modifiche alla fase 1

- `manifest.CHIAVI` + `cron`, `settings`, `sequences`; validazione di ciascuna.
- `modulo_applica`: sincronizza pianificazioni, parametri di default e sequenze; alla
  disinstallazione toglie pianificazioni e sequenze del modulo (i parametri restano, come i dati).
- `ModelView`: `chatter`, `tracked_fields`, `sequence_field`, `list_group_by`, `list_sum`,
  `kanban_*`, `calendar_*`, `graph`, `reports`, `import_key`; `save_model` traccia le modifiche.
- Dettaglio a due colonne quando `chatter = True` (una su mobile).
- `docker-compose.yml`: servizio `worker`; `deploy/nginx.conf`: location `internal` per gli
  allegati; `Dockerfile`: Pango.
- Dipendenze nuove: `openpyxl`, `weasyprint`. Nessuna nuova dipendenza frontend.

## Test

Per ogni servizio, test del kernel come in fase 1 più l'uso da `todo`:

- worker: lavoro eseguito, ritentato, fallito; `skip_locked` (marcato `postgres`, saltato su
  SQLite); pianificazione accodata una volta sola con due worker; SIGTERM;
- parametri: precedenza azienda → globale → default; pagina impostazioni; tipi;
- sequenze: formato, azzeramento annuale, concorrenza (Postgres);
- allegati: download consentito/negato secondo il record, limiti, nome ripulito;
- chatter: tracciamento da vista e da API, follower, email solo ai follower e solo per i
  messaggi, accodata nel worker;
- attività: pianifica, fatta → messaggio, "le mie attività", promemoria;
- viste: raggruppamento con totali, kanban con spostamento e permessi, calendario mese e
  settimana, grafico (dati aggregati e SVG), export CSV/XLSX, import con prova a secco ed errori;
- report: HTML del report sempre, PDF se WeasyPrint è disponibile;
- Properties: form, lista, filtro, API, obbligatorietà, per azienda;
- `todo`: installazione vergine con tutto acceso.

Si aggiunge un job di test su **Postgres** (container `postgres:16` dedicato) per i casi di
concorrenza: SQLite non li rappresenta.

## Fuori scope (fasi successive)

Email in entrata e risposte via mail, notifiche in tempo reale (websocket), messaggistica
interna (Discuss), firma digitale dei documenti, report con editor visuale, Properties
"per record padre", viste pivot, gantt e mappa, attività ricorrenti, multi-lingua.

## Decisioni da confermare

1. **Coda di lavori nel DB, scritta nel kernel** — *raccomandata*. Alternative: Celery +
   Redis (standard, ma un servizio in più da gestire per ogni cliente, e sul server Redis non
   c'è); `django-q2` (coda su ORM già pronta, ma è una dipendenza in più per ~300 righe di
   codice, e il cron dei manifest va scritto comunque). Il kernel ne ha bisogno di poco:
   accoda, ritenta, pianifica.
2. **PDF con WeasyPrint** — *raccomandato*: i report sono template Django con il CSS del theme.
   Alternative: Chromium headless (resa perfetta, ma immagine Docker molto più pesante);
   ReportLab (nessuna dipendenza di sistema, ma i layout si scrivono in Python).
3. **Email del chatter: solo in uscita** in questa fase — *raccomandato*. Le risposte via mail
   (casella IMAP o webhook del provider) richiedono infrastruttura per cliente.
4. **Grafici in SVG dal server** — *raccomandato*, niente librerie JS (coerente con la fase 1).
   Alternativa: Chart.js vendorizzato (interattivo, tooltip, ma una dipendenza frontend).
5. **Properties per modello** (e non per record padre come Odoo) — *raccomandato* in fase 2.
6. **Tre piani 2a, 2b, 2c** in quest'ordine — *raccomandato*.
7. **Test di concorrenza su Postgres** in un container dedicato — *raccomandato*; serve Docker
   sulla macchina che esegue i test (c'è).
