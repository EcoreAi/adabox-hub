"""Azioni solo POST e login (richiesta 17 di Zen Park): a sessione scaduta il POST non porta al login con `next`
uguale all'azione (dopo l'accesso un GET lì dava 405), e il login non va mai a una vista solo POST."""
import re
import time
from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
from django.contrib.auth.models import User
from django.urls import get_resolver, resolve, reverse
from django.utils import timezone

from core import due_fattori as df2

PASSWORD = "giusta12345!"
CAMBIA = "/azienda/cambia/"

pytestmark = pytest.mark.django_db


@pytest.fixture
def mario():
    return User.objects.create_user("mario", "mario@example.com", PASSWORD)


def _next(location):
    parti = urlsplit(location)
    assert parti.path == reverse("login")
    return parse_qs(parti.query).get("next", [None])[0]


def test_post_senza_accesso_torna_al_next_del_form(client):
    r = client.post(reverse("core:cambia_azienda"), {"azienda": "1", "next": "/vendite/"})
    assert r.status_code == 302 and _next(r["Location"]) == "/vendite/"


def test_post_senza_accesso_usa_il_referer_dello_stesso_sito(client):
    r = client.post(reverse("core:cambia_azienda"), {"azienda": "1"}, headers={"Referer": "http://testserver/magazzino/?q=a"})
    assert _next(r["Location"]) == "/magazzino/?q=a"


def test_post_senza_accesso_ignora_referer_e_next_di_altri_siti(client):
    r = client.post(reverse("core:cambia_azienda"), {"azienda": "1"}, headers={"Referer": "http://altro.example/x/"})
    assert _next(r["Location"]) == "/"
    r = client.post(reverse("core:cambia_azienda"), {"next": "https://altro.example/x/"})
    assert _next(r["Location"]) == "/"


def test_next_verso_un_altra_azione_solo_post_diventa_home(client):
    r = client.post(reverse("core:cambia_azienda"), {"next": reverse("core:azienda_predefinita")})
    assert _next(r["Location"]) == "/"
    r = client.post(reverse("core:cambia_azienda"), {}, headers={"Referer": "http://testserver" + CAMBIA})
    assert _next(r["Location"]) == "/"


def test_post_htmx_senza_accesso_chiede_il_login_a_pagina_intera(client):
    r = client.post(reverse("core:cambia_azienda"), {"next": "/vendite/"}, headers={"HX-Request": "true"})
    assert r.status_code == 204 and _next(r["HX-Redirect"]) == "/vendite/"


def test_get_con_accesso_resta_405_e_il_post_funziona(client, mario):
    client.force_login(mario)
    assert client.get(reverse("core:cambia_azienda")).status_code == 405
    r = client.post(reverse("core:cambia_azienda"), {"azienda": "0", "next": "/vendite/"})
    assert r.status_code == 404                      # l'azienda non esiste: la vista è arrivata a lavorare
    assert client.post(reverse("core:azienda_predefinita"), {}).status_code != 405


def test_login_con_next_a_un_azione_solo_post_va_alla_home(client, mario):
    r = client.post(reverse("login") + f"?next={CAMBIA}", {"username": "mario", "password": PASSWORD})
    assert r.status_code == 302 and r.url == reverse("core:home")


def test_login_con_next_normale_va_a_quella_pagina(client, mario):
    r = client.post(reverse("login") + "?next=/vendite/", {"username": "mario", "password": PASSWORD})
    assert r.status_code == 302 and r.url == "/vendite/"


def test_login_gia_collegato_non_va_all_azione_solo_post(client, mario):
    client.force_login(mario)
    r = client.get(reverse("login") + f"?next={CAMBIA}")
    assert r.status_code == 302 and r.url == reverse("core:home")


def test_due_passaggi_con_next_a_un_azione_solo_post_va_alla_home(client, mario):
    df = df2.prepara(mario)
    df.attiva_dal = timezone.now()
    df.save(update_fields=["attiva_dal"])
    r = client.post(reverse("login") + f"?next={CAMBIA}", {"username": "mario", "password": PASSWORD})
    assert r.url == reverse("due_fattori_accesso")
    # anche un `next` rimasto in sessione da prima (sessione aperta con una versione vecchia) non porta all'azione
    sessione = client.session
    sessione["due_fattori_attesa"]["next"] = CAMBIA
    sessione.save()
    r = client.post(reverse("due_fattori_accesso"), {"codice": pyotp.TOTP(df2.segreto(df)).at(time.time())})
    assert r.status_code == 302 and r.url == reverse("core:home")


def _viste_solo_post():
    trovate = {}

    def scorri(resolver, prefisso=""):
        for p in resolver.url_patterns:
            if hasattr(p, "url_patterns"):
                scorri(p, prefisso + str(p.pattern))
            elif getattr(p.callback, "solo_post", False):
                trovate[p.callback] = prefisso + str(p.pattern)
    scorri(get_resolver())
    return trovate


# Indirizzi che il test non sa ricostruire dal pattern: nessuno. Se ne servisse uno, va nominato qui.
NON_VERIFICABILI = set()


def test_nessuna_azione_solo_post_rimanda_al_login_con_se_stessa(client):
    viste = _viste_solo_post()
    controllate, saltate = 0, set()
    for vista, pattern in viste.items():
        # un indirizzo concreto: i parametri (<int:pk>, <slug>…) si riempiono con valori qualunque
        percorso = "/" + re.sub(r"<(?:int:|slug:|str:|uuid:)?[^>]*>", "1", pattern.replace("^", "").replace("$", ""))
        try:
            risolta = resolve(percorso)
        except Exception:
            saltate.add(pattern)
            continue
        if risolta.func is not vista:
            saltate.add(pattern)
            continue
        r = client.post(percorso, {})
        assert r.status_code == 302, percorso
        assert _next(r["Location"]) != percorso, percorso
        controllate += 1
    assert saltate <= NON_VERIFICABILI, sorted(saltate - NON_VERIFICABILI)
    assert controllate == len(viste) - len(saltate) and controllate >= 150


def test_azioni_moduli_senza_accesso_tornano_alla_pagina_di_partenza(client):
    for nome in ("moduli_azione", "moduli_attivazione", "moduli_carica", "moduli_scarica", "moduli_licenza",
                 "moduli_sincronizza"):
        url = reverse("core:" + nome)
        assert resolve(url).func.solo_post, nome
        r = client.post(url, {"next": "/vendite/"})
        assert r.status_code == 302 and _next(r["Location"]) == "/vendite/", nome


def test_e_solo_post_vede_percorsi_codificati_e_senza_barra_finale():
    from core.decoratori import e_solo_post
    assert e_solo_post("/azienda/cambia/")
    assert e_solo_post("/azienda/cambia")
    assert e_solo_post("/azienda/cambia?x=1")
    assert e_solo_post("/azienda/%63ambia/")
    assert e_solo_post("/azienda/%63ambia")
    assert not e_solo_post("/vendite/")
    assert not e_solo_post("/non/esiste")


def test_le_azioni_convertite_sono_segnate():
    for nome, args in (("cambia_azienda", []), ("azienda_predefinita", []), ("token_nuovo", []), ("token_revoca", [1]),
                       ("apertura_app", [])):
        assert getattr(resolve(reverse("core:" + nome, args=args)).func, "solo_post", False), nome
