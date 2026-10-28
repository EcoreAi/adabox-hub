"""Viste personalizzabili per richiesta (hook usato da Studio), campi personalizzati singoli nei layout, testata."""
import copy

import pytest
from django.contrib.contenttypes.models import ContentType

from core.models import Azienda, CampoPersonalizzato
from core.registry import hooks
from core.viste import personalizza, registry


@pytest.fixture
def personalizzazioni(monkeypatch):
    funzioni = []
    monkeypatch.setattr(personalizza, "_funzioni", funzioni)
    return funzioni


@pytest.fixture
def campo(db):
    return CampoPersonalizzato.objects.create(modello=ContentType.objects.get_for_model(Azienda), nome="settore",
                                              label="Settore", tipo="testo")


def test_senza_personalizzazioni_la_vista_e_la_stessa(rf, personalizzazioni):
    vista = registry.per_modello(Azienda)
    assert vista.personalizzata(rf.get("/")) is vista


def test_copia_con_attributi_ammessi(rf, personalizzazioni):
    vista = registry.per_modello(Azienda)
    personalizzazioni.append(lambda v, r: {"list_display": ["nome", "email"], "buttons": ["x"]})
    copia = vista.personalizzata(rf.get("/"))
    assert copia is not vista and copia.originale is vista
    assert copia.list_display == ["nome", "email"] and vista.list_display == ["nome", "partita_iva", "citta", "attiva"]
    assert copia.buttons == vista.buttons                       # attributo non ammesso: ignorato


def test_personalizzazione_rotta_non_blocca(client, superuser, personalizzazioni):
    personalizzazioni.append(lambda v, r: 1 / 0)
    assert client.get("/core/aziende/").status_code == 200


def test_lista_form_dettaglio_personalizzati(client, superuser, personalizzazioni, campo):
    az = Azienda.objects.get(pk=1)
    az.email, az.proprieta = "info@prima.it", {"settore": "Edilizia"}
    az.save()
    personalizzazioni.append(lambda v, r: {
        "list_display": ["nome", "email", "prop_settore"],
        "etichette": {"email": "Posta", "nome": "Ragione sociale"},
        "form_layout": [("Essenziale", ["nome", ("email", "prop_settore")])],
    } if v.model is Azienda else {})
    lista = client.get("/core/aziende/").content.decode()
    assert "Posta" in lista and "Ragione sociale" in lista and "Settore" in lista and "Edilizia" in lista
    assert "Partita IVA" not in lista
    form = client.get(f"/core/aziende/{az.pk}/modifica/").content.decode()
    assert "Essenziale" in form and "Ragione sociale" in form and 'name="prop_settore"' in form
    assert "Altre informazioni" not in form and 'name="telefono"' not in form
    r = client.post(f"/core/aziende/{az.pk}/modifica/", {"nome": "Nuovo nome", "email": "a@b.it",
                                                          "prop_settore": "Servizi"})
    az.refresh_from_db()
    assert r.status_code == 302 and az.nome == "Nuovo nome" and az.proprieta["settore"] == "Servizi"
    assert az.telefono == ""                                     # campi tolti dal form: invariati
    dettaglio = client.get(f"/core/aziende/{az.pk}/").content.decode()
    assert "Ragione sociale" in dettaglio and "Servizi" in dettaglio and "Altre informazioni" not in dettaglio


def test_campo_in_lista_non_duplicato(client, superuser, personalizzazioni, campo):
    campo.in_lista = True
    campo.save()
    personalizzazioni.append(lambda v, r: {"list_display": ["nome", "prop_settore"]})
    assert client.get("/core/aziende/").content.decode().count(">Settore<") == 1


def test_voci_testata(client, superuser, monkeypatch, settings, tmp_path):
    monkeypatch.setattr(hooks, "_testata", [])
    (tmp_path / "voce.html").write_text('<span id="voce-prova">voce</span>')
    motori = copy.deepcopy(settings.TEMPLATES)
    motori[0]["DIRS"] = [*motori[0]["DIRS"], str(tmp_path)]
    settings.TEMPLATES = motori                                  # assegnazione: Django ricrea i motori
    hooks.voce_testata("voce.html", permission="core.view_azienda")
    hooks.voce_testata("voce.html", permission="core.view_azienda")      # idempotente
    assert client.get("/core/aziende/").content.decode().count('id="voce-prova"') == 1
    client.logout()
    assert hooks.voci_testata(type("R", (), {"user": type("U", (), {"is_authenticated": False})()})()) == []
