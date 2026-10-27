# adabox-hub — piano di implementazione, fase 2a: i servizi del kernel

**Goal:** dare al kernel i servizi trasversali che le app usano senza scrivere infrastruttura: lavori in background e
pianificazioni, parametri e pagina impostazioni, sequenze, allegati privati, chatter (messaggi, note, follower,
tracciamento, email in uscita e in entrata), attività pianificate. `todo` 1.1.0 li usa tutti dichiarando attributi.

**Spec:** `docs/superpowers/specs/2026-10-27-adabox-hub-fase2-kernel-completo-design.md` (sezione 2a).

**Architecture:** tutto in `core/`, un modulo Python per servizio (`lavori.py`, `parametri.py`, `sequenze.py`,
`allegati.py`, `chatter/`, `attivita.py`), modelli generici con `content_type` + `object_id`. Il controllo dei permessi
sui record passa sempre dalla `ModelView` del modello (`registry.per_modello`): azienda corrente e permessi Django,
come in fase 1. Nessuna dipendenza nuova (IMAP con `imaplib`, email con `email`/`django.core.mail`).

**Regole per chi esegue:** come nel piano di fase 1 (test prima, suite verde, un commit per task, commit in italiano
chiusi con la riga `Co-Authored-By` del modello che li scrive, push a fine task).

**Scostamenti dalla spec decisi qui:**
1. Il pannello del chatter lo include direttamente `dettaglio.html` quando `vista.chatter` è vero (layout a due
   colonne), invece di passare da `hooks.sezione_dettaglio`: le sezioni registrate restano nella colonna principale.
2. `object_id` dei modelli generici è `PositiveBigIntegerField` (i pk sono `BigAutoField`).

---

## Mappa dei file

| File | Responsabilità |
|---|---|
| `core/models.py` | + `Lavoro`, `Pianificazione`, `Parametro`, `Sequenza`, `Allegato`, `Messaggio`, `Follower`, `EmailRicevuta`, `TipoAttivita`, `AttivitaPianificata` |
| `core/generici.py` | `ct_di(obj)`, `record_di(ct, pk)`, `vista_e_oggetto(request, ct_id, pk, permesso)` |
| `core/lavori.py` | `accoda`, `esegui_uno`, `pianifica_scadute`, `intervallo`, `prossima` |
| `core/management/commands/worker.py` | ciclo del worker |
| `core/parametri.py` | `leggi`, `scrivi`, `definizioni` |
| `core/sequenze.py` | `prossimo`, `crea_per_azienda` |
| `core/allegati.py` | `salva`, `valida`, storage privato |
| `core/chatter/` | `__init__.py` (`scrivi`, `traccia`, `segui`, `follower_di`), `email.py` (uscita), `entrata.py` (`ricevi`, IMAP) |
| `core/attivita.py` | `pianifica`, `segna_fatta`, `mie`, promemoria |
| `core/viste/chatter.py` | viste HTMX del pannello (messaggi, note, allegati, follower, attività) |
| `core/registry/manifest.py`, `core/management/commands/modulo_applica.py` | chiavi `cron`, `settings`, `sequences` |
| `core/templates/core/chatter/*.html`, `core/templates/core/impostazioni.html`, `core/templates/core/attivita_mie.html`, `core/templates/core/email/*.txt|html` | interfaccia |
| `addons/todo/` | 1.1.0: chatter, tracciamento, numero da sequenza, cron promemoria, parametro |
| `docker-compose.yml`, `deploy/nginx.conf`, `deploy/test-postgres.sh`, `README.md` | deploy e test su Postgres |

---

### Task 1: Impianto — settings, manifest esteso, generici, test su Postgres — fatto

- Settings: `LAVORI_SINCRONI` (default `DEBUG`; `True` sotto pytest via `pytest-env`), `PRIVATE_MEDIA_ROOT`
  (`BASE_DIR/private`), `ALLEGATI_MAX_MB` (20), `EMAIL_RISPOSTE` (vuoto), `IMAP_URL` (vuoto), `SITO_URL`
  (base assoluta per i link nelle email, default `http://localhost:8000`). `.env.example`, `.gitignore` (`private/`).
- `manifest.py`: chiavi `cron`, `settings`, `sequences` con validazione (tipi, `ogni` in `^\d+[mhd]$`, `alle` `HH:MM`,
  funzione puntata, chiavi uniche, `tipo` dei settings tra quelli ammessi, `scelte` obbligatorie per `scelta`,
  `formato` con `{numero}`).
- `core/generici.py`: risoluzione `content_type`/record e controllo con la `ModelView` (404 se fuori azienda o senza
  vista, 403 senza permesso).
- Marker pytest `postgres` (saltato se il DB non è Postgres) e `deploy/test-postgres.sh` (container `postgres:16-alpine`
  usa e getta, `DATABASE_URL=... pytest -m postgres`).
- Test: manifest con le nuove chiavi (validi e non), generici.

### Task 2: Lavori in background e worker — fatto

- `Lavoro` (spec). `accoda(funzione, ritardo=0, max_tentativi=3, azienda=None, utente=None, **argomenti)`: con
  `LAVORI_SINCRONI` esegue subito (stesso codice di `esegui_uno`, errori propagati solo nei test) e registra comunque
  la riga; altrimenti `in_coda`.
- `esegui_uno()`: prende il primo `in_coda` con `esegui_dopo <= now` (`select_for_update(skip_locked=True)` dove
  supportato), `in_corso`, esegue fuori dalla transazione di presa, `fatto` o ritenta con backoff 1/5/30 min.
- `manage.py worker [--una-volta]`: ciclo con pausa 2 s, SIGTERM/SIGINT → finisce il lavoro in corso ed esce.
- `/core/lavori/`: `ModelView` superuser in sola lettura, filtro stato, bottone "Riprova".
- Test: sincrono, coda, ritentativi e fallimento, `--una-volta`, funzione inesistente → `fallito`; Postgres: due
  worker non prendono lo stesso lavoro.

### Task 3: Pianificazioni (cron)

- `Pianificazione`: `modulo`, `nome`, `funzione`, `ogni`, `alle`, `attiva`, `prossima_esecuzione`, `ultima_esecuzione`.
- `modulo_applica`: crea/aggiorna dal manifest all'installazione e all'aggiornamento (chiave = modulo + nome),
  rimuove alla disinstallazione. Il kernel ha le proprie (promemoria attività, posta in entrata) create da migrazione.
- `pianifica_scadute()` chiamata dal worker a ogni giro: per le scadute accoda il lavoro e calcola la prossima
  (`alle` per i giornalieri, fuso `Europe/Rome`), nella stessa transazione con `select_for_update(skip_locked=True)`.
- Admin: attiva/disattiva. Test: calcolo della prossima esecuzione, una sola accodata, sincronizzazione dal manifest.

### Task 4: Parametri e pagina Impostazioni

- `Parametro` (spec), `parametri.leggi(chiave, azienda=None)` con precedenza azienda → globale → default del
  manifest (o `KeyError` se la chiave non è dichiarata), `scrivi`, conversione per tipo.
- `/impostazioni/` (permesso `core.change_parametro`): una card per modulo installato con `settings`, form generata,
  "per questa azienda" per i `per_azienda`. `settings_url` assente → ancora del modulo su `/impostazioni/`.
- Test: precedenze, tipi, pagina e permessi.

### Task 5: Sequenze

- `Sequenza` (spec, unica per `codice` + `azienda`), `prossimo(codice, azienda)` con `select_for_update`, formato con
  `{anno}`, `{mese}`, `{numero:05d}`, azzeramento annuale. Creazione dal manifest per ogni azienda e alla creazione di
  una nuova `Azienda` (signal). `ModelView.sequence_field = ("campo", "codice")`.
- Test: formato, azzeramento, nuova azienda, assegnazione dalla vista; Postgres: 20 thread → 20 numeri distinti.

### Task 6: Allegati privati

- `Allegato` generico, file in `PRIVATE_MEDIA_ROOT/allegati/<anno>/<mese>/<uuid>-<nome>`, `valida` (dimensione,
  estensioni vietate, nome ripulito).
- `POST /allegati/carica/<ct>/<pk>/` (permesso `change` sul record), `GET /allegati/<pk>/` (permesso `view` sul record;
  `FileResponse`, oppure `X-Accel-Redirect` verso `/_privati/` se `ALLEGATI_X_ACCEL=True`), `POST /allegati/<pk>/elimina/`.
- `deploy/nginx.conf`: `location /_privati/ { internal; alias /app/private/; }`; volume `./private`.
- Test: caricamento, download consentito/negato (azienda diversa → 404), limiti, X-Accel.

### Task 7: Chatter — messaggi, note, follower, tracciamento, pannello

- `Messaggio`, `Follower` (spec). `chatter.scrivi(obj, autore, corpo, tipo, allegati=())`, `traccia(obj, vecchi, utente)`
  (etichette dei campi e valori resi come nel dettaglio), `segui/smetti`.
- `ModelView.chatter`, `tracked_fields`; `save_model` e l'API PATCH tracciano; la creazione scrive "Creato" e rende
  follower il creatore.
- Pannello in `dettaglio.html` (colonna destra): campo di scrittura (Nota / Messaggio), allegati, follower,
  elenco messaggi a pagine (HTMX). Viste in `core/viste/chatter.py`.
- `AziendaView` con `chatter = True` e `tracked_fields = ["attiva", "nome"]` come banco di prova.
- Test: tracciamento da vista e API, follower automatici, permessi (fuori azienda → 404), paginazione.

### Task 8: Email in uscita

- Un `messaggio` (non nota né tracciamento) accoda `chatter.email.notifica(messaggio_id)`: una email per follower
  attivo con email, escluso l'autore. `Message-ID` `<msg-<pk>-<uuid>@<host>>` salvato su `Messaggio.message_id`;
  `Reply-To` `risposte+<token>@dominio` se `EMAIL_RISPOSTE`, token = `ct.pk` firmato con `django.core.signing`.
- Template testo + HTML (`core/email/notifica.*`), link assoluto con `SITO_URL`.
- Test (`mail.outbox`): destinatari, header, token verificabile, nota → nessuna email.

### Task 9: Email in entrata

- `EmailRicevuta` (spec). `chatter.entrata.ricevi(raw_bytes)`: parse, idempotenza su `Message-ID`, abbinamento
  (`In-Reply-To`/`References` → `Messaggio.message_id`, poi token nell'indirizzo `To`/`Delivered-To`), mittente =
  utente attivo con quella email e permesso `view` sul record (azienda: una consentita a cui il record appartiene),
  corpo testo senza citazioni, allegati → `Allegato`. Esito su `EmailRicevuta`.
- `chatter.entrata.leggi_casella()`: IMAP da `IMAP_URL`, `UNSEEN`, `ricevi` per ciascuna, segna `\Seen`; pianificazione
  del kernel ogni 2 minuti (non fa nulla senza `IMAP_URL`).
- `/core/email/`: `ModelView` superuser in sola lettura.
- Test con email costruite a mano: abbinamento per header e per token, token falsificato, mittente sconosciuto o senza
  permesso, citazione tolta (italiano e inglese), HTML senza testo, allegato, doppione; IMAP con `imaplib` finto.

### Task 10: Attività pianificate

- `TipoAttivita` (dati iniziali da migrazione), `AttivitaPianificata` (spec). `attivita.pianifica`, `segna_fatta`
  (messaggio nel chatter + cancellazione), `mie(utente)`.
- Pannello del chatter: elenco con colore per scadenza, "Pianifica" (form in linea), "Fatta", "Annulla".
- `/attivita/` "Le mie attività" raggruppate (scadute, oggi, prossime), voce nel launcher con contatore, contatore
  nell'header via `piattaforma` (una query, solo per utenti autenticati).
- Pianificazione del kernel "Promemoria attività" ogni giorno alle 07:00: una email per utente con le attività di oggi
  e scadute.
- Test: pianifica/fatta/annulla, permessi, pagina, contatore, promemoria.

### Task 11: `todo` 1.1.0

- Manifest 1.1.0: `cron` (promemoria scadenze delle attività `todo` usando il parametro), `settings`
  (`giorni_preavviso`), `sequences` (`todo.attivita`, `ATT/{anno}/{numero:04d}`).
- Migrazione `0002`: campo `numero` (vuoto per le esistenti, poi riempito da `post_upgrade`).
- `AttivitaView`: `chatter = True`, `tracked_fields = ["stato", "assegnatario", "scadenza"]`,
  `sequence_field = ("numero", "todo.attivita")`, `numero` in lista e in sola lettura.
- `hooks.post_upgrade(modulo, da)`: da `1.0.x` numera le attività esistenti.
- Test: chatter e tracciamento su un'attività; installazione vergine 1.1.0; **aggiornamento** 1.0.0 → 1.1.0 nel
  sottoprocesso (copia della 1.0.0 dal commit della fase 1, installa, sostituisci con la 1.1.0, `modulo aggiorna`,
  numeri assegnati).

### Task 12: Deploy e documentazione

- `docker-compose.yml`: servizio `worker` (stessa immagine, `python manage.py worker`), volume `./private`;
  `LAVORI_SINCRONI=False` per web e worker.
- README: servizi del kernel (come si usano da un'app), worker e cron, impostazioni, allegati, chatter ed email
  (configurazione `EMAIL_URL`, `EMAIL_RISPOSTE`, `IMAP_URL`, casella con indirizzi `+`), test su Postgres.
- Verifica: suite, `check --deploy`, `deploy/test-postgres.sh`, `docker compose build && up`, worker attivo nei log,
  pulizia dei file creati da root.
