# adabox-hub

Starter Django 5.2 con lo stile grafico "SaaS" di ICHNOBYTE (admin e frontend)
e la sicurezza di base già configurata. Si clona per iniziare un nuovo cliente.

## Avvio in 5 passi

1. Clona e riparti da zero con git:
   ```bash
   git clone <questo-repo> nome-cliente && cd nome-cliente && rm -rf .git && git init
   ```
2. Brand: in `config/settings.py` imposta `THEME` (`brand`, `mark`, `company`, `company_url`, `version`, `nav`).
   Ogni voce di `THEME["nav"]` deve avere un `url_name` esistente: un nome sbagliato
   solleva `NoReverseMatch` su tutte le pagine (voluto: l'errore di configurazione si vede subito).
3. Palette (opzionale): cambia i valori in `theme/static/theme/tokens.css`.
   Verifica il contrasto del primario su bianco (minimo AA 4,5:1).
   Aggiorna anche il colore fisso della favicon in `theme/views.py` (`bg="#1e3a8a"`).
4. L'app `core` è un esempio (modello `Cliente`, home, `/stile/`, `/profilo/`):
   svuotala, rinominala o usala come base.
5. Ambiente:
   ```bash
   python3 -m venv .venv && . .venv/bin/activate
   pip install -r requirements-dev.txt
   cp .env.example .env            # imposta SECRET_KEY
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver
   ```
   Apri `http://127.0.0.1:8000/accounts/login/`, poi `/stile/` (catalogo dei componenti) e `/admin/`.

## Struttura

- `config/` settings unico via `.env`, urls, wsgi.
- `theme/` tutta la grafica: template admin, shell frontend (`theme/base.html`),
  login/lockout/errori, `tokens.css` (colori), `admin.css`, `ui.css`, `ui.js`,
  favicon dinamica con la sigla (`/favicon.svg`). **Non importa nulla da `core` o `config`**:
  si può copiare in un altro progetto così com'è (test `test_portabilita.py`).
- `core/` app di esempio.

## Usare il tema nelle tue pagine

```django
{% extends 'theme/base.html' %}
{% block title %}Titolo · {{ theme.brand }}{% endblock %}
{% block content %}
  <div class="ui-pagehead"><div><h1>Titolo</h1><div class="sub">Sottotitolo</div></div></div>
  <div class="ui-card is-revealed"><div class="ui-card-body">…</div></div>
{% endblock %}
```

Tutti i componenti, con lo snippet da copiare, sono in `/stile/`.

## Sicurezza inclusa

- django-axes: blocco per coppia username+IP. Al 5° tentativo fallito (`AXES_FAILURE_LIMIT`)
  il login risponde HTTP 429 con la pagina di blocco, per 15 minuti (`AXES_COOLOFF_MINUTES`).
  Un login riuscito azzera il conteggio.
- Sessione 30 min rinnovata a ogni richiesta, cookie HttpOnly, `X-Frame-Options: DENY`.
- Con `DEBUG=False`: cookie Secure, `X-Forwarded-Proto` dal proxy, log su file in
  `logs/`, mail agli `ADMINS` sugli errori 500. HSTS spento finché non lo accendi
  tu con `SECURE_HSTS_SECONDS`.

## Produzione

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
pytest
```

## Fuori scope (deliberatamente)

Docker, deploy, CI, reset password via mail, dark mode, lingue oltre l'italiano.
