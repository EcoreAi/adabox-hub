# adabox-hub — piattaforma modulare stile Odoo, fase 1: il kernel

Data: 2026-10-27
Stato: approvato in sessione il 2026-10-27 (decisioni 1-5 della sezione finale confermate)
Precede: `2026-10-09-django-template-design.md` (lo starter da cui nasce il repo)

## Scopo

adabox-hub è un'applicazione gestionale per aziende, di proprietà di ICHNOBYTE,
costruita con Django sopra lo starter `django-template`. Riproduce il modello di
Odoo: una piattaforma (il **kernel**) e delle **app** installabili, aggiornabili e
disinstallabili dall'interfaccia, come i plugin di WordPress. Il prodotto si
rivende per istanza: a ogni cliente si installa un insieme diverso di app, e per
alcuni si sviluppano moduli custom in repository separati.

Questa spec copre la **fase 1**: il kernel minimo e un'app di riferimento (`todo`)
che lo dimostra. Le fasi successive (chatter, attività, kanban, calendario,
report, worker, upload zip, app gestionali) sono elencate in fondo e avranno
spec proprie.

Riferimento funzionale: Odoo 19 Community, con i moduli custom di
`/opt/adaerp` come requisiti già collaudati sul campo. **Sola lettura e solo come
idea**: Odoo Community è LGPL-3, gli addon OCA sono AGPL/LGPL. Non si copia
codice, template, CSS, icone o testi. Si riproducono funzionalità, flussi e UX.

Metro di riuscita della fase 1: con il kernel pronto, un'app come `todo`
(modello, viste, permessi, menu) si scrive in una giornata e si installa con
un comando.

## Decisioni prese

1. **Il kernel è `core`.** Si tiene il nome e la grafica. Il modello di esempio
   `Cliente` e la home con i KPI spariscono; restano `/stile/` e `/profilo/`.
   `theme/` resta intatto e portabile (il test `test_portabilita` continua a
   valere), con una sola aggiunta: HTMX vendorizzato.
2. **Le app sono pacchetti Python in `addons/`**, una cartella per app, con un
   `__manifest__.py` in stile Odoo. Anche le app ufficiali stanno lì: il
   meccanismo è lo stesso per tutti.
3. **Stato di installazione in un file**, `addons/installed.json`, letto dai
   settings per comporre `INSTALLED_APPS`. Django fissa le app all'avvio del
   processo: installare un modulo significa aggiornare il file, migrare in un
   sottoprocesso e ricaricare gunicorn. Il modello `Modulo` in DB è lo specchio
   del file per l'interfaccia, non la fonte di verità all'avvio.
4. **Prima da riga di comando, poi dall'interfaccia.** `manage.py modulo
   installa|aggiorna|disinstalla` fa tutto il lavoro; la pagina `/moduli/`
   lancia lo stesso comando. In fase 1 si installano i moduli già presenti su
   disco; il caricamento di uno zip arriva in fase 4, ma il validatore del
   manifest nasce ora.
5. **Viste dichiarate in Python**, classe `ModelView` sullo stile di
   `ModelAdmin`: lista, form, dettaglio, ricerca, filtri, paginazione,
   permessi, API. È l'equivalente delle viste XML di Odoo e il cuore della
   piattaforma. Il kernel le renderizza con i componenti del theme.
6. **Server-side con HTMX**, nessuna SPA. HTMX (file vendorizzato in `theme/`,
   niente CDN) aggiorna la tabella della lista e gestisce conferme e form
   parziali. Le viste sono dichiarate in Python, non nei template: un client
   diverso in futuro non obbliga a riscrivere le app.
7. **Multi-azienda dal primo giorno, multi-tenant mai.** Un'istanza per
   cliente; dentro l'istanza più aziende (`Azienda`), come in Odoo. I modelli
   di dominio usano `AziendaMixin` e il kernel filtra per l'azienda corrente.
8. **Permessi con i gruppi Django.** Il manifest dichiara i gruppi con i
   permessi; l'installazione li crea. Niente sistema ACL proprio in fase 1.
9. **API JSON generica** per ogni modello registrato, via Django Ninja:
   stessa sintassi per tutte le app, permessi applicati. Serve anche ad
   adabox, che oggi chiama le API di adaerp.
10. **Nomi.** API Python in inglese come Django e come i manifest Odoo
    (`ModelView`, `list_display`, `depends`); modelli, URL, testi e
    documentazione in italiano come il resto del repo.
11. **Postgres in produzione**, SQLite solo in sviluppo e nei test. Già
    supportato da `DATABASE_URL`; con più moduli e migrazioni SQLite non basta.
12. **Backup prima di ogni installazione o aggiornamento**, come fa
    `deploy_moduli.sh` di adaerp. Senza backup riuscito il comando si ferma.
13. **Versione del kernel** in `core/__init__.py` (`__version__`, semver).
    Ogni manifest dichiara `min_core`; un modulo che chiede un kernel più
    recente non si installa.

## Struttura

```
adabox-hub/
├── addons/                         # le app; su disco in sviluppo, volume Docker in produzione
│   ├── installed.json              # stato di installazione (gitignore)
│   ├── contatti/                   # fase 3; qui solo come esempio di dipendenza
│   └── todo/                       # app di riferimento della fase 1
│       ├── __manifest__.py
│       ├── __init__.py
│       ├── apps.py
│       ├── models.py
│       ├── views.py                # ModelView e pagine proprie
│       ├── urls.py                 # solo pagine proprie; le viste dei modelli le monta il kernel
│       ├── forms.py
│       ├── hooks.py                # post_install, post_upgrade, pre_uninstall (facoltativo)
│       ├── migrations/
│       ├── data/                   # fixture dichiarate nel manifest
│       ├── templates/todo/
│       ├── static/todo/icon.svg
│       └── tests/
├── backup/                         # dump del DB prima di installazioni e aggiornamenti (gitignore)
├── config/
│   ├── settings.py                 # ADDONS_DIR, INSTALLED_APPS dinamico, HTMX no, Ninja sì
│   └── urls.py                     # + api, + moduli montati dal registro
├── core/                           # il kernel
│   ├── __init__.py                 # __version__
│   ├── registry/
│   │   ├── bootstrap.py            # SOLO python puro: legge installed.json e i manifest, niente Django
│   │   ├── manifest.py             # schema, validazione, lettura con ast.literal_eval
│   │   ├── modules.py              # scoperta, stati, ordinamento per dipendenze, sync con il DB
│   │   ├── install.py              # installa/aggiorna/disinstalla: backup, stato, sottoprocesso, hook
│   │   ├── reload.py               # ricarica gunicorn o runserver
│   │   ├── groups.py               # gruppi dal manifest
│   │   └── hooks.py                # punti di aggancio (sezioni form, ...)
│   ├── viste/
│   │   ├── base.py                 # ModelView, registro delle viste, URL generati
│   │   ├── lista.py form.py dettaglio.py elimina.py
│   │   ├── filtri.py               # ricerca, filtri, ordinamento, paginazione
│   │   └── widgets.py              # resa dei campi (data, bool, FK, scelta, ...)
│   ├── api/
│   │   ├── __init__.py             # NinjaAPI, auth per sessione e token
│   │   └── modelli.py              # router generato da ogni ModelView con api=True
│   ├── backup.py                   # dump sqlite / pg_dump
│   ├── middleware.py               # azienda corrente
│   ├── models.py                   # Modulo, Azienda, ProfiloUtente, TokenApi
│   ├── mixins.py                   # AziendaMixin
│   ├── context_processors.py       # theme.nav dinamica, app corrente, aziende
│   ├── management/commands/modulo.py
│   ├── templates/core/
│   │   ├── base_app.html           # estende theme/base.html: barra dell'app + selettore azienda
│   │   ├── launcher.html           # home: griglia delle app
│   │   ├── moduli.html             # pagina Moduli (superuser)
│   │   ├── vista/lista.html _tabella.html form.html dettaglio.html _conferma.html
│   │   ├── stile.html profilo.html
│   │   └── partials/_menu_app.html _aziende.html
│   └── tests/
├── theme/                          # invariato, più static/theme/vendor/htmx.min.js
├── deploy/
│   ├── entrypoint.sh               # exec gunicorn (serve per il SIGHUP)
│   └── nginx.conf
└── docs/superpowers/specs/
```

## Manifest

File `addons/<slug>/__manifest__.py`: un solo dizionario letterale. Si legge con
`ast.literal_eval`, mai con `import`: leggere un manifest, anche da uno zip
caricato, non deve eseguire codice.

```python
{
    "name": "To-Do",
    "summary": "Attività personali e di squadra con scadenze",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "todo/icon.svg",
    "menu": [
        {"label": "Attività", "url_name": "todo:attivita_lista", "permission": "todo.view_attivita"},
        {"label": "Tag", "url_name": "todo:tag_lista", "permission": "todo.view_tag"},
    ],
    "groups": {
        "To-Do / Utente": ["todo.view_attivita", "todo.add_attivita", "todo.change_attivita", "todo.view_tag"],
        "To-Do / Responsabile": ["todo.*"],
    },
    "data": ["data/tag.json"],
    "demo": ["data/demo.json"],
    "hooks": "todo.hooks",
    "settings_url": None,
}
```

| Chiave | Obbligatoria | Regole |
|---|---|---|
| `name` | sì | testo mostrato nel launcher e nella pagina Moduli |
| `summary` | no | una riga |
| `version` | sì | semver `X.Y.Z`; se maggiore di quella installata il modulo è "da aggiornare" |
| `author`, `category` | no | testo |
| `depends` | no | slug di altri moduli; devono essere installati prima, in ordine topologico. Cicli = errore |
| `min_core` | sì | `X.Y`; confrontata con `core.__version__` |
| `application` | no, default `False` | `True` = compare nel launcher e nella nav dell'header |
| `icon` | no | percorso static (`<slug>/icon.svg`) o nome di icona dello sprite del theme |
| `menu` | no | voci con `label`, `url_name` (deve risolversi, come in `THEME["nav"]`), `permission` facoltativa |
| `groups` | no | nome gruppo → lista di permessi `app.codename`; `app.*` = tutti i permessi dei modelli dell'app |
| `data` | no | fixture caricate a ogni installazione e aggiornamento; devono essere idempotenti (pk fissi) |
| `demo` | no | fixture caricate solo con `--demo` |
| `hooks` | no | modulo Python con `post_install(modulo)`, `post_upgrade(modulo, da_versione)`, `pre_uninstall(modulo)` |
| `settings_url` | no | nome URL della pagina impostazioni dell'app |

Lo **slug** è il nome della cartella e del pacchetto Python: `^[a-z][a-z0-9_]{2,30}$`.
Nomi riservati: `core`, `theme`, `config`, `admin`, `api`, `accounts`, `static`,
`media`, `moduli`, `django`, `test`, `tests`. Chiavi sconosciute nel manifest
sono un errore (si vede subito un refuso).

Lo stesso validatore (`core.registry.manifest.valida(percorso)`) è esposto come
`manage.py modulo verifica <percorso>` e sarà usato dall'upload zip in fase 4.

## Registro dei moduli

### Avvio

`core/registry/bootstrap.py` è Python puro, importabile dai settings prima che
Django sia configurato:

```python
ADDONS_DIR = BASE_DIR / "addons"
sys.path.insert(0, str(ADDONS_DIR))
INSTALLED_APPS = [
    "theme", "django.contrib.admin", ..., "axes", "ninja", "core",
    *bootstrap.moduli_installati(ADDONS_DIR),
]
```

`moduli_installati` legge `installed.json`:

```json
{"schema": 1, "installed": ["contatti", "todo"]}
```

e restituisce gli slug nell'ordine del file (che è già topologico, lo scrive il
kernel). Uno slug senza cartella o senza manifest valido viene **saltato con un
warning** sul log, mai un crash all'avvio: la pagina Moduli lo mostrerà come
"mancante". File assente = nessun modulo installato.

### Stati

Modello `core.Modulo`: `slug` (unico), `nome`, `versione_installata`,
`versione_disponibile`, `stato`, `application`, `installato_il`, `aggiornato_il`,
`gruppi_creati` (JSON), `ultimo_errore`.

| Stato | Significato |
|---|---|
| `disponibile` | cartella e manifest validi su disco, non nel file di stato |
| `installato` | nel file di stato e in `INSTALLED_APPS`, versione uguale al manifest |
| `da_aggiornare` | installato, ma il manifest dichiara una versione maggiore |
| `mancante` | nel file di stato ma cartella assente o manifest rotto |
| `errore` | ultima operazione fallita; dettaglio in `ultimo_errore` |

La sincronizzazione disco → DB (`core.registry.modules.sincronizza()`) gira a
ogni apertura della pagina Moduli, alla fine di ogni comando `modulo` e con
`manage.py modulo sincronizza`. Mai in `AppConfig.ready()`: lì le tabelle
possono non esistere.

### Comandi

`manage.py modulo <sottocomando>`:

| Comando | Effetto |
|---|---|
| `lista` | tabella slug, nome, versione installata/disponibile, stato |
| `verifica <percorso>` | valida un manifest e la struttura della cartella, exit 1 se non valido |
| `installa <slug> [<slug>...] [--demo] [--riavvia]` | vedi flusso sotto; risolve e installa anche le dipendenze mancanti, chiedendo conferma (o `--si`) |
| `aggiorna <slug>|--tutti [--riavvia]` | per i moduli `da_aggiornare` |
| `disinstalla <slug> [--elimina-dati] [--riavvia]` | rifiuta se altri moduli installati dipendono da `slug` |
| `sincronizza` | allinea il DB al disco |

### Flusso di installazione

1. **Validazione**: manifest, `min_core`, dipendenze (installate o nella stessa
   richiesta), slug non riservato, cartella importabile.
2. **Backup del DB** in `backup/<data>-pre-installa-<slug>.{sqlite3,dump}`.
   SQLite: copia del file con l'API di backup di sqlite3. Postgres: `pg_dump -Fc`
   (l'immagine Docker include `postgresql-client`). Si tengono gli ultimi
   `BACKUP_CONSERVA` (default 10). Backup fallito = stop.
3. **Stato**: scrive `installed.json` con i nuovi slug in ordine topologico
   (scrittura atomica: file temporaneo e `rename`).
4. **Sottoprocesso** `manage.py _modulo_applica installa <slug>...`: è un
   processo nuovo, quindi legge il file aggiornato e ha i nuovi moduli in
   `INSTALLED_APPS`. Esegue, per ogni modulo in ordine: `migrate <slug>`,
   `loaddata` delle fixture `data` (e `demo` se richiesto), creazione gruppi,
   `hooks.post_install`, aggiornamento della riga `Modulo`. Con `DEBUG=False`
   anche `collectstatic --noinput`. Log su stdout e in `logs/moduli.log`.
5. **Errore**: si ripristina il file di stato precedente, la riga `Modulo` va in
   `errore` con lo stack, il DB resta com'è (su Postgres ogni migrazione è
   transazionale; il backup del passo 2 copre il resto). Il comando esce con 1.
6. **Ricarica** se `--riavvia` o se lanciato dalla pagina Moduli
   (`core.registry.reload.richiedi()`).

**Aggiornamento**: stessi passi, con `hooks.post_upgrade(modulo, da_versione)`
al posto di `post_install`, gruppi riallineati (permessi aggiunti o tolti,
gruppi rinominati non gestiti in fase 1), fixture `data` ricaricate.

**Disinstallazione**: `hooks.pre_uninstall`, rimozione dei gruppi elencati in
`gruppi_creati`, rimozione dello slug dal file di stato. Senza `--elimina-dati`
le tabelle restano (stato `disponibile`, flag "dati presenti" in pagina). Con
`--elimina-dati`: backup, poi `migrate <slug> zero` **prima** di togliere lo slug
dal file, perché serve ancora in `INSTALLED_APPS`.

### Ricarica del processo

`RELOAD_STRATEGY` in `.env`:

- `gunicorn` (default in produzione): si legge il pid del master dal pidfile
  (`GUNICORN_PIDFILE`, default `/tmp/gunicorn.pid`, scritto da gunicorn con
  `--pid`) e gli si manda `SIGHUP`: il master rialza i worker con il codice
  nuovo. Il pidfile serve perché il comando può partire sia da un worker sia da
  un sottoprocesso della pagina Moduli, e `getppid()` darebbe processi diversi.
  `deploy/entrypoint.sh` fa `exec gunicorn ... --pid /tmp/gunicorn.pid`.
- `runserver` (sviluppo): si aggiorna la data di modifica di
  `config/settings.py`; lo StatReloader di runserver riavvia da solo.
- `none`: non fa nulla e la pagina dice di riavviare a mano.

Durante la ricarica la pagina Moduli mostra "riavvio in corso" e interroga
`/moduli/stato/` con HTMX finché il processo risponde con la nuova lista.

## Settings e URL

`config/settings.py`:

- `ADDONS_DIR`, `sys.path`, `INSTALLED_APPS` dinamico come sopra.
- `BACKUP_DIR = BASE_DIR / "backup"`, `BACKUP_CONSERVA = env.int(default=10)`.
- `RELOAD_STRATEGY = env(default="gunicorn" if not DEBUG else "runserver")`.
- `MIDDLEWARE` + `core.middleware.AziendaCorrenteMiddleware` dopo
  `AuthenticationMiddleware`.
- `context_processors` + `core.context_processors.piattaforma`.
- `THEME["nav"]` non si imposta più a mano: la riempie il kernel.
- `LOGIN_REDIRECT_URL = "core:home"` (il launcher).

`config/urls.py`:

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    ...auth come oggi...,
    path("api/v1/", core.api.api.urls),
    path("", include("theme.urls")),
    path("", include("core.urls")),            # launcher, moduli, stile, profilo, cambio azienda
    *core.registry.urls.patterns_moduli(),     # un prefisso per modulo installato
]
```

`patterns_moduli()` restituisce, per ogni modulo installato in ordine,
`path("<slug>/", include((viste_generate + urls_proprie, slug)))`, dove
`viste_generate` sono gli URL delle `ModelView` registrate dal modulo e
`urls_proprie` è `urlpatterns` di `<slug>/urls.py` se esiste. Namespace = slug.
Un modulo non può montare URL fuori dal suo prefisso.

## Modelli del kernel

- **`Azienda`**: `nome`, `partita_iva`, `codice_fiscale`, `indirizzo`, `cap`,
  `citta`, `provincia`, `email`, `telefono`, `logo` (ImageField), `attiva`.
  La migrazione iniziale di `core` ne crea una da `THEME["brand"]`.
- **`ProfiloUtente`**: OneToOne con `User`, `aziende` (M2M), `azienda_predefinita`
  (FK). Creato da signal alla creazione dell'utente, con tutte le aziende attive.
- **`AziendaMixin`** (astratto): `azienda = FK(Azienda, PROTECT)`, con
  `objects` manager normale e `Meta.indexes` sull'FK. I modelli di dominio
  delle app lo usano salvo i dati condivisi tra aziende (tag, tipi, parametri).
- **Azienda corrente**: `request.azienda`, dal campo `azienda_id` in sessione
  o dalla predefinita del profilo; `POST /azienda/<pk>/` la cambia, se è tra le
  consentite. Il selettore compare nella barra dell'app solo se l'utente ne ha
  più d'una.
- **`Modulo`**: vedi sopra. Esposto nell'admin Django in sola lettura, con il
  link alla pagina `/moduli/`.
- **`TokenApi`**: `utente`, `nome`, `chiave` (hash), `creato`, `ultimo_uso`,
  `attivo`. Generato dal profilo utente; mostrato in chiaro una sola volta.

## `ModelView`

```python
from core.viste import ModelView, registry

@registry.register
class AttivitaView(ModelView):
    model = Attivita
    slug = "attivita"                      # default: model_name; dà gli URL e i nomi
    verbose_name = "Attività"              # default: Meta del modello
    list_display = ["titolo", "scadenza", "assegnatario", "stato"]
    list_filter = ["stato", "assegnatario", "tag"]
    search_fields = ["titolo", "descrizione"]
    ordering = ["-scadenza"]
    per_page = 50
    form_layout = [
        ("Generale", ["titolo", ("scadenza", "assegnatario"), "descrizione"]),
        ("Classificazione", ["tag", "stato"]),
    ]
    form_class = None                      # ModelForm custom, facoltativo
    readonly_fields = ["creato"]
    company_field = "azienda"              # None = modello globale, nessun filtro
    actions = ["archivia"]                 # azioni di massa sulla lista
    buttons = ["segna_fatta"]              # bottoni nella testata del dettaglio
    api = True
    api_fields = None                      # default: campi del form + pk + readonly

    def get_queryset(self, request): ...   # default: filtro azienda + ordering
    def archivia(self, request, queryset): ...     # action, ritorna messaggio
    def segna_fatta(self, request, obj): ...       # button, ritorna redirect o messaggio
```

Cosa produce il kernel per ogni `ModelView` registrata, nel namespace del modulo:

| URL | Nome | Vista | Permesso |
|---|---|---|---|
| `<slug>/` | `<slug>_lista` | lista con ricerca, filtri, ordinamento per colonna, paginazione; `?partial=1` restituisce solo `_tabella.html` per HTMX | `view` |
| `<slug>/nuovo/` | `<slug>_nuovo` | form | `add` |
| `<slug>/<pk>/` | `<slug>_dettaglio` | layout in sola lettura, bottoni, sezioni aggiunte da altri moduli | `view` |
| `<slug>/<pk>/modifica/` | `<slug>_modifica` | form | `change` |
| `<slug>/<pk>/elimina/` | `<slug>_elimina` | conferma (HTMX modale) e POST | `delete` |
| `<slug>/azione/<nome>/` | `<slug>_azione` | POST con i pk selezionati | quello dichiarato dall'azione, default `change` |
| `<slug>/<pk>/bottone/<nome>/` | `<slug>_bottone` | POST | idem |

Regole:

- **Permessi**: `has_view/add/change/delete_permission(request, obj=None)`
  usano i permessi Django del modello; sovrascrivibili. Lista e dettaglio
  nascondono i bottoni che l'utente non può usare. L'oggetto fuori dall'azienda
  corrente è un 404, non un 403.
- **Ricerca e filtri**: `?q=` cerca `icontains` sui `search_fields`;
  `?f_<campo>=<valore>` per i `list_filter` (bool, scelte, FK, date con
  `da`/`a`); `?o=<campo>` o `-<campo>` per l'ordinamento, solo su campi in
  `list_display`; `?p=<n>` pagina. Tutto conservato nei link di paginazione.
- **Resa dei campi** (`widgets.py`): bool come pill, date in `d/m/Y`, FK come
  link al dettaglio se quel modello ha una `ModelView`, scelte con la label,
  `None` come "—". Un metodo `col_<campo>(self, obj)` sulla view sovrascrive la
  resa di una colonna.
- **Form**: `ModelForm` generata dai campi del `form_layout` (o `form_class`),
  resa con i componenti `ui-input/ui-select/ui-textarea` del theme a partire dal
  layout a sezioni e righe (una tupla = campi affiancati). Errori sotto il
  campo. Alla creazione, `company_field` viene impostato da `request.azienda`.
- **Sezioni di dettaglio** (punto di aggancio): un altro modulo chiama
  `hooks.sezione_dettaglio(model="todo.Attivita", template="x/_sezione.html",
  order=50, permission="x.view_y")` nel `ready()` della sua app. Il dettaglio
  include le sezioni registrate, nell'ordine, con `obj` nel contesto. È
  l'equivalente, in fase 1, dell'aggiungere una tab a una form altrui.
- **Template**: `core/vista/lista.html`, `_tabella.html`, `form.html`,
  `dettaglio.html`, `_conferma.html`, estendono `core/base_app.html`. Una
  `ModelView` può indicare `template_lista`, `template_form`,
  `template_dettaglio` propri.

## Navigazione e pagine del kernel

- **`core/base_app.html`** estende `theme/base.html` e aggiunge, sotto
  l'header del theme, la **barra dell'app**: nome dell'app corrente, le sue
  voci di `menu` filtrate per permesso, il selettore azienda. I template delle
  app estendono questo, non `theme/base.html`.
- **`theme.nav`** la riempie `core.context_processors.piattaforma`: una voce per
  ogni modulo installato con `application=True` che l'utente può vedere (almeno
  una voce di menu permessa), `url_name` = prima voce di menu. Il context
  processor del theme resta com'è: `core` importa `theme`, mai il contrario.
- **App corrente**: dedotta dal namespace di `request.resolver_match`.
- **Launcher `/`** (`core:home`): griglia delle app installate con icona, nome e
  summary, stessa logica di visibilità. Empty state con link a `/moduli/` per
  il superuser.
- **`/moduli/`** (superuser): card per ogni modulo con nome, summary, versione,
  stato, dipendenze, bottoni Installa / Aggiorna / Disinstalla (con scelta
  "elimina dati"). Il bottone lancia il comando in un sottoprocesso con
  `--riavvia`, mostra il log in pagina e poi interroga `/moduli/stato/`.
  Caricamento zip: fase 4.
- **`/stile/`** resta e cresce con gli esempi dei componenti nuovi (barra
  dell'app, tabella con filtri, form a sezioni, modale di conferma).
- **`/profilo/`** aggiunge la gestione dei token API e l'azienda predefinita.

## API

`core.api` con Django Ninja, montata su `/api/v1/`, documentazione su
`/api/v1/docs` (solo utenti autenticati).

- **Autenticazione**: sessione Django (stesso dominio, con CSRF) oppure
  `Authorization: Bearer <token>` (`TokenApi`). Il token eredita permessi e
  aziende dell'utente; `X-Azienda: <pk>` sceglie l'azienda corrente tra quelle
  consentite, altrimenti la predefinita.
- **Endpoint generati** per ogni `ModelView` con `api=True`, in
  `/api/v1/<modulo>/<slug>/`: `GET` lista (`q`, `f_*`, `o`, `p`, `per_page`,
  massimo 200), `POST`, `GET /<pk>/`, `PATCH /<pk>/`, `DELETE /<pk>/`. Stessi
  filtri, stesso queryset e stessi permessi della `ModelView`.
- **Schema**: generato dai campi (`api_fields`); FK come pk più campo
  `<nome>_display`; errori di validazione come `422` con la mappa campo → errori,
  stesse regole della form.
- **Endpoint fissi**: `GET /api/v1/me/` (utente, aziende, moduli visibili),
  `GET /api/v1/moduli/` (superuser).

## App di riferimento `todo`

Serve a dimostrare il kernel e resta un'app ufficiale. Modelli:

- `Tag(nome, colore)`: globale (senza azienda).
- `Attivita(AziendaMixin)`: `titolo`, `descrizione`, `scadenza` (date, null),
  `assegnatario` (FK User, null), `stato` (`aperta`, `in_corso`, `fatta`,
  `annullata`), `tag` (M2M), `creato`, `creato_da`.

Due `ModelView` come nell'esempio sopra, action `archivia` (stato annullata su
più righe), button `segna_fatta`, gruppi "To-Do / Utente" e "To-Do /
Responsabile", fixture `data/tag.json` con tre tag, `demo/demo.json` con dieci
attività, `hooks.post_install` che assegna il gruppo Utente a tutti gli utenti
attivi (così dopo l'installazione l'app è subito usabile).

Non ha `urls.py` proprio: tutto viene dalle `ModelView`. Mostra che un'app
minima non scrive né viste né template.

## Docker e deploy

- `Dockerfile`: `postgresql-client`, `deploy/entrypoint.sh` come `CMD`
  (`collectstatic`, `migrate`, poi `exec gunicorn ... --workers 3`).
- `docker-compose.yml`: volumi `./addons:/app/addons` e `./backup:/app/backup`
  oltre al codice; `RELOAD_STRATEGY=gunicorn`.
- `.gitignore`: `addons/installed.json`, `backup/`, `media/`.
- Il `README` descrive: struttura, come si scrive un'app, come si installa da
  CLI e da `/moduli/`, come si fa un backup e un ripristino.

## Test (`pytest-django`)

Kernel:

- `core/tests/test_manifest.py`: manifest valido; chiave sconosciuta, slug
  riservato, versione non semver, dipendenza ciclica, `min_core` troppo alta →
  errore con messaggio chiaro; un manifest con codice (chiamata di funzione)
  viene rifiutato senza essere eseguito.
- `core/tests/test_bootstrap.py`: `moduli_installati` con file assente, slug
  mancante su disco (saltato con warning), ordine conservato; il modulo non
  importa Django (`runpy` in namespace pulito).
- `core/tests/test_install.py`: installazione di un modulo di prova in una
  `addons` temporanea: backup creato, file di stato scritto in ordine
  topologico, gruppi creati con i permessi giusti e `app.*` espanso, fixture
  caricate, hook chiamato, riga `Modulo` aggiornata; migrazione che fallisce →
  stato ripristinato, riga in `errore`, exit 1; disinstalla con dipendenti →
  rifiutata; `--elimina-dati` toglie le tabelle.
- `core/tests/test_reload.py`: strategia `none` non chiama nulla; `gunicorn`
  manda SIGHUP al ppid (monkeypatch di `os.kill`).
- `core/tests/test_modelview.py`: con un modello di prova registrato: tutti
  gli URL generati rispondono; permessi (utente senza `view` → 403, senza `add`
  → bottone assente e POST 403); ricerca, filtri, ordinamento, paginazione;
  `?partial=1` restituisce solo la tabella; oggetto di un'altra azienda → 404;
  creazione imposta `azienda`; `col_<campo>` sovrascrive la colonna; sezione
  di dettaglio registrata da un altro modulo compare nell'ordine dato.
- `core/tests/test_api.py`: token valido e revocato; CRUD completo; `422` sui
  dati non validi; filtri e paginazione; `X-Azienda` non consentita → 403;
  endpoint assente per `ModelView` con `api=False`.
- `core/tests/test_nav.py`: `theme.nav` mostra solo le app con una voce
  permessa; launcher coerente; barra dell'app con il menu giusto.
- `core/tests/test_azienda.py`: cambio azienda consentito e non; selettore
  visibile solo con più aziende.

App `todo`: `addons/todo/tests/` copre modelli, le due view, action, button,
gruppi, fixture, e un test di **installazione vergine**: DB vuoto, `modulo
installa todo --demo`, poi login con un utente del gruppo Utente, lista con le
dieci attività demo, API che le restituisce, `disinstalla --elimina-dati`.

Theme: `test_portabilita` invariato, più un test che `htmx.min.js` è servito e
incluso in `base.html`.

## Scostamenti dalla spec dello starter

- **HTMX** entra (vendorizzato, versione fissa), contro la decisione 3 dello
  starter. Serve per lista, filtri e modali senza una SPA; resta l'unica
  dipendenza frontend.
- **Django Ninja** e **Pillow** (per il logo) entrano in `requirements.txt`.
- `core` non è più un'app di esempio ma il kernel: il `README` dello starter non
  vale più per questo repo.
- `theme/base.html` carica `vendor/htmx.min.js` prima di `ui.js`.

## Fuori scope (fasi successive)

- **Fase 2, kernel completo**: chatter (messaggi, note, follower, allegati,
  email in uscita), attività generiche, sequenze, kanban, calendario, grafico,
  raggruppamenti nella lista, report PDF, worker con cron e code, parametri e
  pagine impostazioni, import ed export CSV/XLSX, campi Properties.
- **Fase 3, prime app**: contatti, calendario, crm, helpdesk, progetti e
  timesheet. `todo` passa sulle attività generiche del kernel.
- **Fase 4, distribuzione**: upload zip da `/moduli/`, script che impacchetta un
  modulo, test di installazione vergine per ogni app in ordine di dipendenze,
  firma dei pacchetti, indice dei moduli approvati.
- **Fase 5, gestionale**: prodotti, vendite, magazzino, acquisti, fatturazione
  (SDI come modulo a parte), HR, spese.
- **Fase 6**: Studio (viste modificabili in DB), documenti, discuss.

Non previsti: multi-tenant, website ed eCommerce (esiste `sito_adabox`), POS,
produzione, dark mode, lingue oltre l'italiano.

## Da confermare prima del piano

1. Nomi dell'API Python in inglese e tutto il resto in italiano (decisione 10).
2. Django Ninja al posto di Django REST Framework (più leggero, schema
   automatico, tipizzato).
3. Pagina Moduli nel frontend (`/moduli/`, con il theme) e non dentro l'admin
   Django, che mostra solo le righe in sola lettura.
4. HTMX vendorizzato nel theme.
5. Nome definitivo dell'app di riferimento: `todo`.
