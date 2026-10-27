# django-template — starter Django con lo stile SIEE

Data: 2026-10-09
Stato: approvato a voce in sessione, da rivedere su file

## Scopo

Un progetto Django da clonare per iniziare il lavoro per un nuovo cliente
partendo dallo stile grafico di SIEE-ENAS (admin e frontend) e da una
configurazione di sicurezza di base già fatta. Non è un clone di SIEE: porta
solo la grafica e l'impianto minimo.

Origine dello stile (sola lettura, nessuna modifica a quel repo):
`SIEE_Enas/prototype/static/css/siee.css`,
`SIEE_Enas/prototype/static/admin/css/siee-admin.css`,
`SIEE_Enas/prototype/templates/admin/base_site.html`,
`SIEE_Enas/prototype/core/templates/{base.html,login.html,partials/*}`.

## Decisioni prese

1. **Forma:** starter project da clonare, con tutta la grafica in una app
   `theme/` autosufficiente (nessun import da `core` o `config`). Se un domani
   serve, `theme/` diventa un pacchetto pip senza rifarlo.
2. **Contenuto:** grafica + sicurezza di base (axes, cookie secure, HSTS
   opzionale, logging). Niente simple_history, filters, deploy, Docker, CI.
3. **Nessuna dipendenza frontend esterna:** niente Bootstrap, HTMX, Alpine,
   DataTables. CSS grid/flex nativi e un `ui.js` di poche decine di righe.
4. **Brand in `settings.THEME`** (testo, sigla, azienda). **Colori nei token
   CSS**, non in settings: cambiare palette è un lavoro di design che tocca
   anche hover, tint e contrasto.
5. Versioni: Python 3.12, Django 5.2 LTS, django-environ, django-axes,
   psycopg (Postgres) con SQLite come default per partire senza DB.
6. Lingua: italiano (`LANGUAGE_CODE = 'it'`, `TIME_ZONE = 'Europe/Rome'`).

## Struttura

```
django-template/
├── README.md                 # procedura nuovo cliente in 5 passi
├── requirements.txt          # Django 5.2, django-environ, django-axes, psycopg[binary], gunicorn
├── requirements-dev.txt      # pytest, pytest-django
├── .env.example              # ogni variabile commentata
├── .gitignore
├── manage.py
├── pytest.ini
├── config/
│   ├── settings.py           # unico, tutto via env
│   ├── urls.py
│   └── wsgi.py
├── theme/                    # TUTTA la grafica, nessun import dal resto
│   ├── apps.py
│   ├── context_processors.py # espone `theme` (= settings.THEME) ai template
│   ├── templates/
│   │   ├── admin/base_site.html
│   │   ├── theme/base.html
│   │   ├── theme/partials/_header.html
│   │   ├── theme/partials/_footer.html
│   │   ├── theme/partials/_icons.html
│   │   ├── registration/login.html
│   │   ├── registration/password_change_form.html
│   │   ├── registration/password_change_done.html
│   │   ├── lockout.html
│   │   ├── 400.html 403.html 404.html 500.html csrf_failure.html
│   └── static/theme/
│       ├── tokens.css        # solo design token
│       ├── admin.css         # override admin Django (importa tokens.css)
│       ├── ui.css            # componenti frontend (importa tokens.css)
│       ├── ui.js             # dropdown profilo, menu mobile, toast
│       └── icons/favicon.svg, favicon.ico, apple-touch-icon.png
├── core/                     # app di esempio, da svuotare o rinominare
│   ├── models.py             # Cliente(nome, email, attivo, creato)
│   ├── admin.py              # list_display, list_filter, search_fields
│   ├── views.py              # home, stile, profilo
│   ├── urls.py
│   ├── templates/core/home.html, stile.html, profilo.html
│   └── tests/
├── theme/tests/
└── docs/superpowers/specs/
```

## `theme/` nel dettaglio

### Token (`tokens.css`)

Un solo `:root` con i valori presi da `siee.css`, prefisso `--ui-`:

- Brand: `--ui-primary #1e3a8a`, `--ui-primary-lift #2945a3`,
  `--ui-primary-hover-dark #152a63`, `--ui-primary-tint rgba(30,58,138,.10)`.
- Testo: `#1d1d1f`, `#6e6e73`, `#86868b`.
- Superfici: `#ffffff`, `#f5f5f7`; bordo `#e5e5ea`, `rgba(0,0,0,.10)`.
- Semantici: success `#34c759`, warning `#ff9f0a`, danger `#ff3b30` con tint al 12%.
- Radii: card 18, modal 12, input 8, pill 980.
- Ombre: card, header, dropdown, modal (stessi valori di SIEE).
- Font: system stack sans e mono (nessun webfont).
- Motion: ease-out, ease-bounce, transition 0.2s.

Non si porta il ciano ENAS (`--color-brand-enas`): è del cliente.

### Admin (`admin.css` + `admin/base_site.html`)

Riscrittura di `siee-admin.css` con i token `--ui-*` al posto dei `--siee-*`
duplicati. Sovrascrive le custom property native di Django 5.x
(`--primary`, `--body-bg`, `--header-bg`, `--button-bg`, ...), header 60px con
blur, badge quadrato con la sigla. Dark mode disattivata come in SIEE (stessi
valori per `data-theme="dark"`).

`base_site.html`: titolo `{{ title }} · {{ theme.brand }}`, branding con
`theme.mark` e `theme.brand · Admin`, `nav-global` vuoto, favicon.

### Frontend (`ui.css`, prefisso `ui-`)

Portato da `siee.css`: reset/base, layout (`.ui-container`, `.ui-shell`),
header con blur e dropdown profilo, nav semplice a link con stato attivo,
page head, KPI grid, card, bottoni (primary, secondary, danger, sm, icon),
input/select/textarea, pill/badge (success, warning, danger, neutral),
tabelle, empty state, alert, toast, login, footer, animazioni link e righe,
`prefers-reduced-motion`, responsive ≤768px.

Non portato: mega-dropdown, scope bar, PWA, back button mobile, generatore
grafici, heatmap, viste salvate, breadcrumb drill-down, DataTables, HTMX,
Alpine combobox, KPI inline, compaction, nascondi-azioni mobile.

### Icone

Sprite SVG inline in `_icons.html`, solo quelle usate dai componenti portati:
user, lock, tool, chevron-down, menu, x, check, alert-triangle, search,
arrow-left, download, log-out, zap.

### `base.html`

Blocchi: `title`, `head_extra`, `content`, `scripts`. Include icons, header
(solo se autenticato), messages come alert, footer con anno, azienda e
versione (`theme.version`, default vuoto). Nessuna dipendenza da URL name di
`core`: la nav del header legge una lista `THEME["nav"]` di
`{"label", "url_name"}` e la risolve con `{% url %}`; se vuota non mostra
nulla. Il link "Amministrazione" nel dropdown compare se `user.is_staff`.

### `context_processors.theme`

Restituisce `{"theme": {**DEFAULTS, **settings.THEME}}` con default
`brand="Progetto"`, `mark="PR"`, `company=""`, `company_url=""`,
`version=""`, `nav=[]`.

## `config/settings.py`

Tutto via `django-environ`, file `.env` opzionale.

Sempre:
- `INSTALLED_APPS`: `theme` prima di `django.contrib.admin` (per
  sovrascrivere `admin/base_site.html`), poi contrib standard, `axes`, `core`.
- `AUTHENTICATION_BACKENDS` con `axes.backends.AxesStandaloneBackend` primo.
- Axes: `AXES_FAILURE_LIMIT=5`, `AXES_COOLOFF_TIME=15 min`,
  `AXES_LOCKOUT_PARAMETERS=[["username","ip_address"]]`,
  `AXES_RESET_ON_SUCCESS=True`, `AXES_LOCKOUT_TEMPLATE="lockout.html"`.
  Limite e minuti sovrascrivibili via env.
- Password validators standard (min 8, comune, numerica, simile allo username).
- `SESSION_COOKIE_AGE=1800`, `SESSION_SAVE_EVERY_REQUEST=True`,
  `SESSION_COOKIE_HTTPONLY=True`, `X_FRAME_OPTIONS="DENY"`,
  `SECURE_CONTENT_TYPE_NOSNIFF=True`.
- `LOGIN_URL="login"`, `LOGIN_REDIRECT_URL="core:home"`,
  `LOGOUT_REDIRECT_URL="login"`.
- Logging: console sempre. Con `DEBUG=False`: file rotante `logs/app.log`
  (INFO) e `logs/error.log` (ERROR), `mail_admins` su `django.request` ERROR.
  `ADMINS` da env (`ADMINS=Nome:mail@x.it,Altro:y@x.it`).
- `DATABASES` da `DATABASE_URL`, default `sqlite:///db.sqlite3`.
- `STATIC_ROOT=staticfiles`, `STATICFILES_DIRS=[]` (gli static stanno nelle app).

Solo con `DEBUG=False`:
- `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True` (env può spegnere).
- `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO","https")`.
- `SECURE_SSL_REDIRECT` default False; `SECURE_HSTS_SECONDS` default 0,
  `INCLUDE_SUBDOMAINS` e `PRELOAD` default False: HSTS si accende
  esplicitamente quando il 443 è verificato.
- `CSRF_TRUSTED_ORIGINS` da env.

## `config/urls.py`

`admin/`, `accounts/login/`, `accounts/logout/`,
`accounts/password_change/` (+ `done`) con le viste di `django.contrib.auth`
e i template in `theme/templates/registration/`, poi `include("core.urls")`.
Handler 400/403/404/500 puntano ai template di `theme`.

## `core/` (esempio)

- `/` home: page head "Benvenuto", 3 KPI card (clienti totali, attivi,
  creati negli ultimi 30 giorni), tabella degli ultimi 10 clienti, empty
  state se nessuno. Richiede login.
- `/stile/` catalogo: una pagina statica con ogni componente di `ui.css` e il
  relativo snippet HTML in un `<pre>`. Richiede login.
- `/profilo/`: nome, cognome, email modificabili con `ModelForm` su `User`.
- `Cliente` in admin con `list_display`, `list_filter(attivo, creato)`,
  `search_fields(nome, email)`, `date_hierarchy=creato`.

## Test (`pytest-django`)

- `theme/tests/test_portabilita.py`: nessun file in `theme/` contiene
  `from core` / `import core` / `from config` / `import config`.
- `theme/tests/test_pagine.py`: login, lockout, 404 rispondono con il
  template giusto e contengono `theme.brand`.
- `core/tests/test_pagine.py`: home, stile, profilo, admin index,
  changelist e change form di `Cliente` → 200 da utente staff; home → 302 da
  anonimo.
- `core/tests/test_axes.py`: 5 login errati → sesto tentativo risponde con
  `lockout.html`.
- `config/tests/test_deploy.py`: `call_command("check", "--deploy")` con
  `DEBUG=False` e settings di produzione non produce warning diversi da
  quelli HSTS (`security.W004`, `W008`).

## README — procedura nuovo cliente

1. Clona il repo nella cartella del cliente, cancella `.git`, `git init`.
2. In `settings.THEME` metti brand, sigla, azienda, nav.
3. Se serve un'altra palette cambia i valori in `theme/static/theme/tokens.css`
   (verifica il contrasto AA del primario su bianco).
4. Svuota o rinomina `core` (o tienilo come punto di partenza).
5. `cp .env.example .env`, `pip install -r requirements.txt`, `migrate`,
   `createsuperuser`, `runserver`. Apri `/stile/` e `/admin/` per verificare.

## Fuori scope

Docker, deploy, CI, reset password via mail, dark mode, i18n oltre
l'italiano, pubblicazione su pip.

## Scostamenti in implementazione

Accettati in revisione finale:

- Favicon servita da una vista (`/favicon.svg`, sigla dal `THEME`) più un redirect
  permanente da `/favicon.ico`, invece di un file statico.
- Aggiunto `403_csrf.html` (pagina dell'errore CSRF nello stile del tema).
- Niente `handler400`…`handler500` espliciti nell'urlconf: gli handler di default di
  Django caricano già `400.html`, `403.html`, `404.html`, `500.html` per nome.
- Il lockout di axes scatta al 5° tentativo fallito (risposta 429), non al sesto.
- Le card compaiono con l'animazione solo se il JS ha messo la classe `js` su `<html>`;
  senza JS sono subito visibili.
- Aggiunto il contenitore `.ui-table-wrap` per lo scroll orizzontale delle tabelle.
- Test dei settings con `runpy` (caricamento in un namespace nuovo) invece del reload
  del modulo; `check --deploy` gira in un sottoprocesso.
