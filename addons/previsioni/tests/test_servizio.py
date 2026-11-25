"""Il client del servizio di previsione e la sua pagina di impostazione."""
import io
import json
import re
import urllib.error
from pathlib import Path

import pytest
from django.contrib.auth.models import User

from core import cifratura, licenza, parametri
from previsioni import servizio
from previsioni.models import ServizioPrevisioni

pytestmark = pytest.mark.django_db


class _Risposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _finto(monkeypatch, risposta=None, errore=None):
    viste = []

    def urlopen(richiesta, timeout=None):
        viste.append(richiesta)
        if errore:
            raise errore
        return _Risposta(json.dumps(risposta or {"ok": True}).encode())
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return viste


def test_senza_url_il_modulo_non_e_attivo():
    assert servizio.url() == "" and servizio.attivo() is False


def test_con_url_e_licenza_e_attivo(monkeypatch):
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080/")
    assert servizio.url() == "http://forecast:8080" and servizio.attivo() is True
    monkeypatch.setattr(licenza, "ammesso", lambda slug: False)
    assert servizio.attivo() is False


def test_la_chiave_va_nell_intestazione_solo_se_c_e(monkeypatch):
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    viste = _finto(monkeypatch)
    assert servizio.chiama("/x", {"a": 1}) == {"ok": True}
    assert not viste[-1].has_header("Authorization")
    ServizioPrevisioni.objects.filter(pk=ServizioPrevisioni.corrente().pk).update(chiave_cifrata=cifratura.cifra("abc"))
    servizio.chiama("/x", {"a": 1})
    assert viste[-1].get_header("Authorization") == "Bearer abc"
    assert viste[-1].full_url == "http://forecast:8080/x"


def test_servizio_giu_messaggio_chiaro(monkeypatch):
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    _finto(monkeypatch, errore=ConnectionRefusedError("rifiutata"))
    with pytest.raises(servizio.ErrorePrevisione, match="Il servizio di previsione non risponde"):
        servizio.chiama("/x", {})


def test_senza_url_chiama_si_rifiuta():
    with pytest.raises(servizio.ErrorePrevisione, match="non è configurato"):
        servizio.chiama("/x", {})


def test_servizio_che_rifiuta(monkeypatch):
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    _finto(monkeypatch, errore=urllib.error.HTTPError("u", 422, "no", {}, io.BytesIO(b"serie troppo corta")))
    with pytest.raises(servizio.ErrorePrevisione, match="serie troppo corta"):
        servizio.chiama("/x", {})


def test_la_pagina_del_servizio_solo_al_global_admin(client):
    normale = User.objects.create_user("norma", "n@example.com", "x")
    client.force_login(normale)
    assert client.get("/previsioni/servizio/").status_code == 403
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    pagina = client.get("/previsioni/servizio/")
    assert pagina.status_code == 200 and "non impostata" in pagina.content.decode()
    assert client.post("/previsioni/servizio/", {"nuova_chiave": "segretissima"}).status_code == 302
    assert cifratura.decifra(ServizioPrevisioni.corrente().chiave_cifrata) == "segretissima"
    pagina = client.get("/previsioni/servizio/").content.decode()
    assert "segretissima" not in pagina and "impostata" in pagina and "non impostata" not in pagina
    client.post("/previsioni/servizio/", {"togli_chiave": "on"})
    assert ServizioPrevisioni.corrente().chiave_cifrata == ""


def test_dentro_una_richiesta_web_si_aspetta_meno_del_worker(monkeypatch):
    """Ruling 27: 25 s per le chiamate fatte dentro una richiesta web (gunicorn ferma il worker a 60 s), 120 s nei
    lavori in background (la notte, «Aggiorna»)."""
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    attese = []

    def urlopen(richiesta, timeout=None):
        attese.append(timeout)
        return _Risposta(b'{"ok": true}')
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    servizio.chiama("/x", {})
    assert attese == [25]                                              # una pagina, Analisi, Ada: dentro la richiesta
    with servizio.in_lavoro():
        servizio.chiama("/x", {})
    servizio.chiama("/x", {})
    assert attese == [25, 120, 25]
    avvio = (Path(__file__).resolve().parents[3] / "deploy" / "entrypoint.sh").read_text()
    assert servizio.TIMEOUT_WEB < int(re.search(r"--timeout (\d+)", avvio).group(1))
