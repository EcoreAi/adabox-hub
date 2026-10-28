import datetime
import json

import pytest
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from core import proprieta
from core.models import Azienda, CampoPersonalizzato, Lavoro, TokenApi


@pytest.fixture
def campi(db):
    ct = ContentType.objects.get_for_model(Azienda)
    crea = CampoPersonalizzato.objects.create
    return {
        "sdi": crea(modello=ct, nome="codice_sdi", label="Codice SDI", obbligatorio=True, in_lista=True, ordine=1),
        "fascia": crea(modello=ct, nome="fascia", label="Fascia", tipo="scelta", scelte="a|Alta\nb|Bassa",
                       filtrabile=True, ordine=2),
        "dal": crea(modello=ct, nome="cliente_dal", label="Cliente dal", tipo="data", ordine=3),
        "vip": crea(modello=ct, nome="vip", label="VIP", tipo="booleano", filtrabile=True, ordine=4),
    }


def _dati(**extra):
    return {"nome": "Acme", "attiva": "on", "prop_codice_sdi": "ABC1234", "prop_fascia": "a",
            "prop_cliente_dal": "2026-01-15", **extra}


def test_form_e_salvataggio(client, superuser, campi):
    html = client.get("/core/aziende/nuovo/").content.decode()
    assert "Altre informazioni" in html and 'name="prop_codice_sdi"' in html and 'name="prop_fascia"' in html
    r = client.post("/core/aziende/nuovo/", _dati(prop_vip="on"))
    assert r.status_code == 302
    acme = Azienda.objects.get(nome="Acme")
    assert acme.proprieta == {"codice_sdi": "ABC1234", "fascia": "a", "cliente_dal": "2026-01-15", "vip": True}


def test_obbligatorio(client, superuser, campi):
    r = client.post("/core/aziende/nuovo/", _dati(prop_codice_sdi=""))
    assert r.status_code == 200 and "ui-field-error" in r.content.decode()


def test_chiavi_estranee_conservate_e_modifica(client, superuser, campi):
    a = Azienda.objects.create(nome="Acme", proprieta={"codice_sdi": "X", "vecchio": 1})
    html = client.get(f"/core/aziende/{a.pk}/modifica/").content.decode()
    assert 'value="X"' in html
    client.post(f"/core/aziende/{a.pk}/modifica/", _dati(prop_codice_sdi="NUOVO"))
    a.refresh_from_db()
    assert a.proprieta["codice_sdi"] == "NUOVO" and a.proprieta["vecchio"] == 1


def test_dettaglio_lista_e_filtri(client, superuser, campi):
    Azienda.objects.create(nome="Alta", proprieta={"codice_sdi": "S1", "fascia": "a", "cliente_dal": "2026-01-15", "vip": True})
    Azienda.objects.create(nome="Bassa", proprieta={"codice_sdi": "S2", "fascia": "b"})
    a = Azienda.objects.get(nome="Alta")
    html = client.get(f"/core/aziende/{a.pk}/").content.decode()
    assert "Codice SDI" in html and "15/01/2026" in html and "Alta" in html
    r = client.get("/core/aziende/")
    assert "Codice SDI" in [c["label"] for c in r.context["colonne"]] and "S2" in r.content.decode()
    assert [o.nome for o, _ in client.get("/core/aziende/", {"f_prop_fascia": "b"}).context["righe"]] == ["Bassa"]
    assert [o.nome for o, _ in client.get("/core/aziende/", {"f_prop_vip": "1"}).context["righe"]] == ["Alta"]


def test_per_azienda(db, campi):
    zeta = Azienda.objects.create(nome="Zeta")
    CampoPersonalizzato.objects.create(modello=ContentType.objects.get_for_model(Azienda), nome="solo_zeta",
                                       label="Solo Zeta", azienda=zeta)
    assert "solo_zeta" not in [d.nome for d in proprieta.definizioni(Azienda, Azienda.objects.get(pk=1))]
    assert "solo_zeta" in [d.nome for d in proprieta.definizioni(Azienda, zeta)]
    assert proprieta.definizioni(Lavoro) == []                        # il modello non li accetta


def test_api(client, campi):
    u = User.objects.create_superuser("api", "api@example.com", "x")
    _, chiaro = TokenApi.genera(u, "t")
    h = {"HTTP_AUTHORIZATION": f"Bearer {chiaro}"}
    r = client.post("/api/v1/core/aziende/", json.dumps({"nome": "Da API", "proprieta": {"codice_sdi": "API1", "fascia": "b"}}),
                    content_type="application/json", **h)
    assert r.status_code == 201 and r.json()["proprieta"]["codice_sdi"] == "API1"
    pk = r.json()["id"]
    r = client.patch(f"/api/v1/core/aziende/{pk}/", json.dumps({"proprieta": {"fascia": "a"}}), content_type="application/json", **h)
    assert r.status_code == 200 and r.json()["proprieta"] == {"codice_sdi": "API1", "fascia": "a", "cliente_dal": None, "vip": False}
    r = client.post("/api/v1/core/aziende/", json.dumps({"nome": "Senza SDI"}), content_type="application/json", **h)
    assert r.status_code == 422 and "prop_codice_sdi" in r.json()["errori"]


def test_validazione_della_definizione(db):
    ct_lavoro = ContentType.objects.get_for_model(Lavoro)
    with pytest.raises(ValidationError) as e:
        CampoPersonalizzato(modello=ct_lavoro, nome="Nome Sbagliato", label="x", tipo="scelta", filtrabile=False).full_clean()
    assert {"modello", "nome", "scelte"} <= set(e.value.message_dict)
    with pytest.raises(ValidationError):
        CampoPersonalizzato(modello=ContentType.objects.get_for_model(Azienda), nome="t", label="T", tipo="testo",
                            filtrabile=True).full_clean()


def test_pagina_campi(client, superuser):
    html = client.get("/core/campi/nuovo/").content.decode()
    opzioni = html[html.index('name="modello"'):html.index("</select>", html.index('name="modello"'))]
    assert "azienda" in opzioni and "lavoro" not in opzioni
    assert "Campi personalizzati" in client.get("/app/").content.decode()


def test_testo_e_conversioni(db, campi):
    a = Azienda(proprieta={"fascia": "b", "cliente_dal": "2026-02-03", "vip": False})
    assert proprieta.testo(campi["fascia"], a) == "Bassa"
    assert proprieta.testo(campi["dal"], a) == "03/02/2026"
    assert proprieta.testo(campi["vip"], a) == "No" and proprieta.testo(campi["sdi"], a) == "—"
    assert proprieta.in_json(campi["dal"], datetime.date(2026, 2, 3)) == "2026-02-03"
