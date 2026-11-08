"""INT-08: l'SDK Python generato si scarica, si importa e lavora davvero contro l'API (trasporto sul client di test)."""
import types

import pytest
from django.core.cache import cache

from core.models import Azienda, TokenApi


def _sdk(client):
    r = client.get("/api/v1/sdk/python/")
    assert r.status_code == 200 and r["Content-Disposition"].endswith('adabox.py"')
    modulo = types.ModuleType("adabox")
    exec(compile(r.content.decode(), "adabox.py", "exec"), modulo.__dict__)        # noqa: S102 - il file appena generato
    return modulo


def _collega(sdk, client, chiaro):
    c = sdk.Adabox("http://testserver", token=chiaro)

    def apri(metodo, url, corpo, intestazioni):
        percorso = url.replace("http://testserver", "")
        extra = {f"HTTP_{k.upper().replace('-', '_')}": v for k, v in intestazioni.items() if k not in ("Content-Type",)}
        r = client.generic(metodo, percorso, corpo or b"", content_type="application/json", **extra)
        return r.status_code, dict(r.headers), r.content
    c._apri = apri
    return c


@pytest.mark.django_db
def test_sdk_generato_funziona(client, superuser):
    cache.clear()
    sdk = _sdk(client)
    assert "Campi: id" in sdk.R_core_aziende.__doc__ and "nome (nome)" in sdk.R_core_aziende.__doc__
    assert not hasattr(sdk, "R_ai_provider")                                  # le viste con segreti non ci sono
    client.logout()
    _, chiaro = TokenApi.genera(superuser, "sdk")
    c = _collega(sdk, client, chiaro)
    assert c.me()["username"] == superuser.username
    nuova = c.core.aziende.crea({"nome": "Via SDK", "partita_iva": "99", "attiva": True})
    assert Azienda.objects.get(pk=nuova["id"]).nome == "Via SDK"
    c.core.aziende.modifica(nuova["id"], {"citta": "Torino"})
    assert c.core.aziende.leggi(nuova["id"])["citta"] == "Torino"
    assert any(a["id"] == nuova["id"] for a in c.core.aziende.tutti(per_page=1))      # paginazione
    with pytest.raises(sdk.ErroreValidazione) as e:
        c.core.aziende.crea({"nome": ""})
    assert "nome" in e.value.errori
    with pytest.raises(sdk.ErroreApi) as e:
        c.core.aziende.leggi(999999)
    assert e.value.stato == 404


@pytest.mark.django_db
def test_sdk_aspetta_col_limite(client, superuser, settings, monkeypatch):
    cache.clear()
    settings.API_LIMITE = "2/m"
    sdk = _sdk(client)
    client.logout()
    _, chiaro = TokenApi.genera(superuser, "sdk")
    c = _collega(sdk, client, chiaro)
    attese = []
    monkeypatch.setattr(sdk.time, "sleep", lambda s: (attese.append(s), cache.clear()))   # «passa» il minuto
    for _ in range(3):
        c.core.aziende.lista()
    assert attese and attese[0] >= 1
