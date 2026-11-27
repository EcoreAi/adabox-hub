"""Il token CSRF per gli script sta nella pagina (<meta name="csrf-token">), non nel cookie: ogni istanza della flotta
dà al cookie un nome suo (deploy/flotta.py, CSRF_COOKIE_NAME), e uno script che legge «csrftoken» riceve 403."""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import Client


def _token_della_pagina(html):
    return re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)


def test_il_token_della_pagina_vale_con_qualunque_nome_del_cookie(superuser, settings):
    settings.CSRF_COOKIE_NAME = "adabox_demo_csrf"                    # come un'istanza della flotta
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(superuser)
    token = _token_della_pagina(browser.get("/profilo/").content.decode())
    assert "adabox_demo_csrf" in browser.cookies and "csrftoken" not in browser.cookies
    corpo = json.dumps({"endpoint": "https://fcm.googleapis.com/fcm/send/xyz", "keys": {}, "disattiva": True})
    assert browser.post("/push/iscrivi/", corpo, content_type="application/json").status_code == 403         # senza token
    assert browser.post("/push/iscrivi/", corpo, content_type="application/json", headers={"X-CSRFToken": token}).status_code != 403


def test_un_tema_che_sostituisce_i_suoi_fogli_non_perde_il_token():
    """Il <meta> è un pezzo a sé (_csrf.html), incluso in ogni pagina accanto a _tema.html: un tema che sostituisce
    _tema.html per i suoi fogli di stile (lo fanno i temi dei moduli) non deve portarsi via il token degli script."""
    radice = Path(settings.BASE_DIR)
    assert "csrf-token" not in (radice / "theme/templates/theme/partials/_tema.html").read_text()
    pagine = [f for cartella in (radice / "theme" / "templates", Path(settings.ADDONS_DIR)) for f in cartella.rglob("*.html")
              if 'include "theme/partials/_tema.html"' in f.read_text(errors="ignore")]
    assert len(pagine) >= 6 and all('include "theme/partials/_csrf.html"' in f.read_text() for f in pagine)


def test_il_token_c_e_solo_per_chi_e_dentro(client, db):
    assert 'name="csrf-token"' not in client.get("/accounts/login/").content.decode()


def test_nessuno_script_legge_il_cookie_con_il_nome_scritto_fisso():
    radici = [Path(settings.BASE_DIR) / "core" / "static", Path(settings.BASE_DIR) / "theme" / "static", *Path(settings.ADDONS_DIR).glob("*/static")]
    legge_il_cookie = re.compile(r"cookie[^\n]{0,120}csrftoken")       # document.cookie.match(/…csrftoken=…/)
    colpevoli = [str(f.relative_to(settings.BASE_DIR)) for radice in radici for f in radice.rglob("*.js")
                 if "vendor" not in f.parts and not f.name.endswith(".min.js") and legge_il_cookie.search(f.read_text(errors="ignore"))]
    assert colpevoli == [], "il token si legge da <meta name=\"csrf-token\">, non dal cookie «csrftoken»"
