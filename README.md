# adabox-hub

Piattaforma gestionale modulare di ICHNOBYTE, costruita con Django 5.2 sopra lo
starter `django-template`. Riproduce il modello di Odoo: un **kernel** (`core`) e
delle **app** in `addons/` che si installano, aggiornano e disinstallano da riga di
comando o dalla pagina `/moduli/`. A ogni cliente la sua istanza, con le sue app.

Spec e piano della fase 1: `docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md`,
`docs/superpowers/plans/2026-10-27-adabox-hub-fase1-kernel.md`.

## Avvio in sviluppo

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                       # imposta SECRET_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py modulo installa todo --demo --si
python manage.py runserver
```

Apri `http://127.0.0.1:8000/`: il launcher mostra le app installate. Poi `/moduli/`
(superuser), `/core/aziende/`, `/api/v1/docs`, `/profilo/` (token API), `/stile/`.

## Struttura

```
addons/            le app: una cartella per app, con __manifest__.py
  installed.json   stato di installazione dell'istanza (non versionato)
  todo/            app di riferimento
backup/            dump del DB prima di ogni installazione/aggiornamento (non versionato)
config/            settings unico via .env; INSTALLED_APPS = kernel + addons installati
core/              il kernel
  registry/        bootstrap (python puro, letto dai settings), manifest, scoperta e stati,
                   installazione, gruppi, ricarica, hook, URL dei moduli
  viste/           ModelView e viste generiche (lista, form, dettaglio, elimina, azioni)
  api/             API JSON (Django Ninja): /api/v1/
  backup.py        sqlite (API di backup) o pg_dump
  models.py        Azienda, ProfiloUtente, Modulo, TokenApi
theme/             grafica (admin e frontend) + htmx vendorizzato; non importa nulla da core
deploy/            entrypoint.sh (gunicorn con pidfile), nginx.conf
```

## Scrivere un'app

Un'app minima non scrive né viste né template: bastano modello, `ModelView` e manifest.
`addons/todo/` è l'esempio completo.

1. **Cartella e manifest** — `addons/<slug>/__manifest__.py`, un solo dizionario letterale
   (si legge con `ast.literal_eval`, mai importato):
   ```python
   {
       "name": "To-Do", "summary": "Attività con scadenze", "version": "1.0.0", "min_core": "1.0",
       "depends": [], "application": True, "icon": "todo/icon.svg",
       "menu": [{"label": "Attività", "url_name": "todo:attivita_lista", "permission": "todo.view_attivita"}],
       "groups": {"To-Do / Utente": ["todo.view_attivita", "todo.add_attivita"], "To-Do / Responsabile": ["todo.*"]},
       "data": ["data/tag.json"], "demo": ["data/demo.json"], "hooks": "todo.hooks",
   }
   ```
   Lo slug (`^[a-z][a-z0-9_]{2,30}$`) è il nome della cartella e del pacchetto. Chiavi
   sconosciute sono un errore. `python manage.py modulo verifica addons/<slug>` lo valida.
2. **Pacchetto Django** — `__init__.py`, `apps.py`, `models.py`, `migrations/`. I modelli
   per azienda ereditano `core.mixins.AziendaMixin`; quelli condivisi (tag, tipi) no.
   Le migrazioni si generano con `ADDONS_FORCE=<slug> python manage.py makemigrations <slug>`
   (la variabile carica il modulo anche se non è ancora installato).
3. **Viste** — in `views.py`:
   ```python
   from core.viste import ModelView, register

   @register
   class AttivitaView(ModelView):
       model = Attivita
       list_display = ["titolo", "scadenza", "stato"]
       list_filter = ["stato"]
       search_fields = ["titolo"]
       form_layout = [("Generale", ["titolo", ("scadenza", "stato")])]   # tupla = campi affiancati
       company_field = "azienda"          # filtro e assegnazione automatica dell'azienda corrente
       actions = ["archivia"]             # metodi (self, request, queryset) -> messaggio
       buttons = ["segna_fatta"]          # metodi (self, request, obj) -> messaggio o HttpResponse
       api = True                         # /api/v1/<slug>/<vista>/

       def col_stato(self, obj): ...      # resa personalizzata di una colonna
   ```
   Il kernel genera sotto `/<slug>/` lista (ricerca, filtri, ordinamento, paginazione con
   HTMX), nuovo, dettaglio, modifica, elimina (modale), azioni e bottoni, con nomi URL
   `<slug>:<vista>_lista|_nuovo|_dettaglio|_modifica|_elimina|_azione|_bottone` e i permessi
   Django del modello. Pagine proprie: `urls.py` del modulo (montato sotto lo stesso prefisso)
   e template che estendono `core/base_app.html`.
4. **Gruppi, fixture, hook** — i gruppi del manifest si creano all'installazione (`app.*` =
   tutti i permessi dell'app); le fixture `data` si caricano a ogni installazione e
   aggiornamento (pk fissi), quelle `demo` solo con `--demo`; `hooks.py` può definire
   `post_install(modulo)`, `post_upgrade(modulo, da_versione)`, `pre_uninstall(modulo)`.
5. **Sezioni su modelli altrui** — nel `ready()` dell'app:
   `core.registry.hooks.sezione_dettaglio("todo.Attivita", "mia_app/_sezione.html", order=50)`.
6. **Test** — in `addons/<slug>/tests/`; per farli girare con la suite aggiungi lo slug a
   `ADDONS_FORCE` in `pytest.ini`.

## Servizi del kernel

Un'app li usa dichiarando attributi o chiamando una funzione: niente viste né template da scrivere.

| Servizio | Come si usa |
|---|---|
| **Chatter** | `ModelView.chatter = True`: pannello con messaggi, note interne, follower, allegati e attività nel dettaglio. `tracked_fields = ["stato", ...]` scrive le modifiche (da form e da API). Da codice: `core.chatter.scrivi(obj, utente, testo)`, `core.chatter.traccia(obj, vecchi, utente)` con `vecchi = core.chatter.valori(obj, campi)` letto prima. |
| **Email** | I *messaggi* (non le note) partono per email ai follower, nel worker. Le risposte tornano nel chatter del record (vedi sotto). |
| **Attività** | Nel pannello: "Pianifica un'attività" (tipo, scadenza, assegnatario). Fatta → voce del chatter. `/attivita/` elenca le proprie; promemoria ogni mattina alle 07:00. Da codice: `core.attivita.pianifica(obj, tipo, utente, scadenza)`. |
| **Allegati** | Nel pannello, o `core.allegati.salva(obj, file, utente)`. File in `private/`, mai pubblici: si scaricano da `/allegati/<pk>/` solo con il permesso di vedere il record. |
| **Sequenze** | Manifest `"sequences": [{"codice": "todo.attivita", "formato": "ATT/{anno}/{numero:04d}", "azzera": "anno"}]` e `ModelView.sequence_field = ("numero", "todo.attivita")`; da codice `core.sequenze.prossimo(codice, azienda)`. |
| **Impostazioni** | Manifest `"settings": [{"chiave": "giorni_preavviso", "label": ..., "tipo": "intero", "default": 2, "per_azienda": True}]`: pagina `/impostazioni/` generata; si leggono con `core.parametri.leggi("todo.giorni_preavviso", azienda)`. |
| **Lavori** | `core.lavori.accoda("app.modulo.funzione", ritardo=0, **argomenti_json)`: eseguito dal worker, con tre tentativi (1, 5, 30 minuti). `/core/lavoro/` per il superuser. |
| **Pianificazioni** | Manifest `"cron": [{"nome": ..., "funzione": "todo.lavori.promemoria_scadenze", "ogni": "1d", "alle": "07:30"}]` (`ogni`: `15m`, `2h`, `1d`). Si attivano e disattivano dall'admin. |

### Worker

`python manage.py worker` esegue lavori e pianificazioni (in Docker è il servizio `worker`). Più worker in
parallelo funzionano su Postgres. In sviluppo `LAVORI_SINCRONI=True` (default con `DEBUG`) esegue i lavori subito,
nella richiesta: il worker serve solo per le pianificazioni. Quando cambiano i moduli installati il worker esce
da solo e Docker lo riavvia con il codice nuovo.

### Posta del chatter

- **Uscita**: `EMAIL_URL` (vedi Produzione) e `SITO_URL` (base dei link, es. `https://hub.cliente.it`).
- **Entrata**: una casella dedicata che accetti gli indirizzi con il `+` (`risposte+qualcosa@cliente.it` arriva in
  `risposte@cliente.it`): `EMAIL_RISPOSTE=risposte@cliente.it` e
  `IMAP_URL=imaps://risposte%40cliente.it:password@mail.cliente.it:993/INBOX`. Ogni 2 minuti il worker legge le
  email non lette e le abbina al record (per `In-Reply-To` o per il token firmato nell'indirizzo); il mittente
  deve essere un utente che vede il record. Esiti in `/core/email/`.

## Comandi `modulo`

| Comando | Effetto |
|---|---|
| `modulo lista` | moduli su disco e installati, versioni, stato |
| `modulo verifica <cartella>` | valida il manifest |
| `modulo installa <slug>... [--demo] [--riavvia] [--si]` | backup, stato, migrazioni, fixture, gruppi, hook; installa anche le dipendenze mancanti (chiede conferma, salvo `--si`) |
| `modulo aggiorna <slug>...` / `--tutti` `[--riavvia]` | per i moduli con versione nuova su disco |
| `modulo disinstalla <slug> [--elimina-dati] [--riavvia] [--si]` | rifiuta se altri moduli ne dipendono; senza `--elimina-dati` le tabelle restano |
| `modulo sincronizza` | allinea la tabella `Modulo` al disco |

Il lavoro vero lo fa `modulo_applica` (uso interno) in un processo nuovo, che legge il file
di stato aggiornato e quindi ha il modulo in `INSTALLED_APPS`. Se fallisce, il file di stato
torna com'era e il modulo va in stato `errore`. Log in `logs/moduli.log`.

La pagina **`/moduli/`** (solo superuser) lancia gli stessi comandi con `--riavvia` e mostra
il log in pagina. `RELOAD_STRATEGY` decide come si ricarica il server: `gunicorn` (SIGHUP al
pid in `GUNICORN_PIDFILE`), `runserver` (tocca `config/settings.py`), `none` (a mano).

## Multi-azienda

Ogni utente ha un `ProfiloUtente` con le aziende consentite e una predefinita (creato in
automatico con tutte le aziende attive). L'azienda corrente (`request.azienda`) si cambia dal
selettore nella barra dell'app; via API con l'header `X-Azienda: <pk>`. Le aziende si
gestiscono da `/core/aziende/`.

## API

`/api/v1/`, documentazione su `/api/v1/docs` (solo utenti autenticati). Autenticazione con la
sessione (stesso dominio, con CSRF) o `Authorization: Bearer <token>`; i token si creano dal
profilo e si vedono in chiaro una volta sola. Per ogni `ModelView` con `api = True`:
`GET` lista (`q`, `f_<campo>`, `o`, `p`, `per_page` fino a 200), `POST`, `GET/PATCH/DELETE
/<pk>/`, con gli stessi permessi e filtri della vista; errori di validazione come `422
{"errori": {...}}`. Fissi: `GET /api/v1/me/`, `GET /api/v1/moduli/` (superuser).

## Backup e ripristino

Prima di ogni installazione, aggiornamento o disinstallazione il kernel salva il DB in
`backup/` (`<data>-pre-<operazione>-<slug>.sqlite3` o `.dump`) e tiene gli ultimi
`BACKUP_CONSERVA` (default 10). Senza backup riuscito l'operazione non parte.

- **SQLite**: ferma il server e copia il file: `cp backup/<file>.sqlite3 db.sqlite3`.
- **Postgres**: `pg_restore --clean --if-exists --dbname "$DATABASE_URL" backup/<file>.dump`.

Dopo un ripristino rimetti `addons/installed.json` coerente con il DB (la riga del modulo
installato prima del backup va tolta a mano) e riavvia.

## Sicurezza inclusa

- django-axes: blocco per coppia username+IP. Al 5° tentativo fallito (`AXES_FAILURE_LIMIT`)
  il login risponde HTTP 429 con la pagina di blocco, per 15 minuti (`AXES_COOLOFF_MINUTES`).
  Un login riuscito azzera il conteggio.
- Sessione 30 min rinnovata a ogni richiesta, cookie HttpOnly, `X-Frame-Options: DENY`.
- Con `DEBUG=False`: cookie Secure, `X-Forwarded-Proto` dal proxy, log su file in
  `logs/`, mail agli `ADMINS` sugli errori 500. HSTS spento finché non lo accendi
  tu con `SECURE_HSTS_SECONDS`.

## Produzione

- Docker: `docker compose up -d --build`. `deploy/entrypoint.sh` esegue `collectstatic` e
  `migrate`, poi `exec gunicorn ... --pid /tmp/gunicorn.pid`: il pidfile serve alla ricarica
  dopo un'installazione (`RELOAD_STRATEGY=gunicorn`, già impostato nel compose).
  `addons/`, `backup/`, `media/` e `private/` (allegati) sono volumi: restano sull'host. Il servizio `worker`
  esegue lavori e pianificazioni; nginx serve gli allegati con `X-Accel-Redirect` (`ALLEGATI_X_ACCEL=True`).
  Installare un modulo nel container:
  `docker compose exec web python manage.py modulo installa <slug> --si --riavvia`.
- Database: Postgres (`DATABASE_URL=postgres://...`); SQLite solo in sviluppo. L'immagine
  include `postgresql-client` per `pg_dump`.

- `SECRET_KEY` ha un default di sviluppo: in produzione va **sempre** impostata in `.env`.
  `python manage.py check --deploy` la segnala (`security.W009`) se resta quella di default.
- Proxy: la configurazione presuppone esattamente **un** reverse proxy fidato (nginx)
  davanti a gunicorn, con queste direttive nel `location` che fa `proxy_pass`:
  ```nginx
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
  ```
  `$proxy_add_x_forwarded_for` aggiunge **in coda** a `X-Forwarded-For` l'IP reale del
  client; le voci a sinistra le ha scritte il client e sono falsificabili. Per questo
  axes (tramite django-ipware, installato con `django-axes[ipware]`) usa
  `AXES_IPWARE_PROXY_COUNT=0` e `IPWARE_STRICT=False`: prende sempre l'ultima voce.
  Non usare `AXES_IPWARE_PROXY_COUNT=1`: con ipware 8 conta i proxy *dentro*
  l'header, quindi restituirebbe la voce scelta dal client (o nessun IP per le
  richieste normali). Con più proxy in catena (es. un bilanciatore davanti a nginx)
  va rivisto il conteggio (`config/tests/test_axes_ip.py`).
  gunicorn deve ascoltare solo su `127.0.0.1` (o socket unix): se l'app è raggiungibile
  direttamente, `X-Forwarded-Proto`/`X-Forwarded-For` sono falsificabili e il blocco
  di axes si aggira cambiando IP dichiarato.
- Mail: senza `EMAIL_URL` le mail (errori 500 agli `ADMINS`) finiscono sulla console.
  In produzione imposta in `.env` per esempio
  `EMAIL_URL=smtp+tls://utente:password@smtp.example.com:587` (`smtp+ssl://` per la 465;
  caratteri speciali nella password vanno codificati, es. `@` → `%40`) e
  `DEFAULT_FROM_EMAIL` con un mittente accettato dal server SMTP. Le mail agli `ADMINS`
  partono solo con `DEBUG=False`.
- Con `DEBUG=False` Django non serve gli static: esegui `python manage.py collectstatic`
  e fai servire `STATIC_ROOT` (`staticfiles/`) da nginx.
- `check --deploy` con la configurazione di default segnala solo `security.W004` (HSTS)
  e `security.W008` (SSL redirect): sono spenti di proposito finché il 443 non è verificato,
  poi si accendono con `SECURE_HSTS_SECONDS` e `SECURE_SSL_REDIRECT` in `.env`.
- Per provare la modalità produzione in locale su http, imposta in `.env`
  `SESSION_COOKIE_SECURE=False` e `CSRF_COOKIE_SECURE=False` (altrimenti il login
  non funziona: il browser non rimanda i cookie Secure su http).

## Portare `theme/` in un altro progetto

`theme/` non importa nulla dal resto del progetto, ma si aspetta che il progetto
che lo ospita abbia:

- `"theme"` in `INSTALLED_APPS` **prima** di `"django.contrib.admin"` (sovrascrive
  i template dell'admin);
- `"theme.context_processors.theme"` in `TEMPLATES[0]["OPTIONS"]["context_processors"]`
  (insieme a `request`, `auth` e `messages`);
- `path("", include("theme.urls"))` nell'urlconf principale (favicon);
- le viste di `django.contrib.auth` con i nomi URL `login`, `logout`,
  `password_change` e `password_change_done` (es. `path("accounts/", include("django.contrib.auth.urls"))`);
- `django.contrib.admin` installato e incluso negli URL: l'header punta a `admin:index`;
- facoltativo: il dizionario `THEME` nei settings (senza, valgono i default di
  `theme/context_processors.py`);
- facoltativo: una route `core:profilo`; se esiste, il menu utente mostra il link Profilo.

## Test

```bash
pytest                    # tutta la suite, compresa l'installazione vergine di todo
pytest -m "not slow"      # senza i test end-to-end
```

I test di concorrenza (worker, pianificazioni, sequenze) girano solo su Postgres:

```bash
deploy/test-postgres.sh           # Postgres usa e getta in Docker, solo i test marcati postgres
deploy/test-postgres.sh -q        # tutta la suite su Postgres
```
