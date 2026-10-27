import datetime

import pytest
from django.utils import timezone

from core.models import Azienda, Lavoro
from core.viste import gruppi, registry


@pytest.fixture
def vista(monkeypatch):
    v = registry.per_modello(Azienda)
    monkeypatch.setattr(v, "list_group_by", ["provincia", "attiva", "nome:mese", "inesistente"])
    monkeypatch.setattr(v, "list_display", ["nome", "provincia", "id"])
    monkeypatch.setattr(v, "list_sum", ["id", "nome"])
    return v


@pytest.fixture
def dati(db):
    Azienda.objects.all().delete()
    for nome, prov, attiva in [("A1", "CA", True), ("A2", "CA", False), ("B1", "MI", True), ("C1", "", True)]:
        Azienda.objects.create(nome=nome, provincia=prov, attiva=attiva)
    return {a.nome: a.pk for a in Azienda.objects.all()}


def test_raggruppabili(vista):
    assert gruppi.raggruppabili(vista) == [("provincia", "Provincia"), ("attiva", "Attiva")]   # nome non è una data
    assert gruppi.somme_ammesse(vista) == ["id"]


def test_lista_raggruppata(client, superuser, vista, dati):
    r = client.get("/core/aziende/", {"g": "provincia"})
    blocchi = r.context["blocchi"]
    assert [(b["etichetta"], b["n"]) for b in blocchi] == [("—", 1), ("CA", 2), ("MI", 1)]
    assert blocchi[1]["somme"][2] == str(dati["A1"] + dati["A2"])
    html = r.content.decode()
    assert 'class="ui-gruppo"' in html and "Raggruppa: Provincia" in html
    assert r.context["totali"][2] == f"{sum(dati.values()):,}".replace(",", ".")


def test_booleani_e_filtri_insieme(client, superuser, vista, dati):
    r = client.get("/core/aziende/", {"g": "attiva", "f_provincia": "CA"})
    assert [(b["etichetta"], b["n"]) for b in r.context["blocchi"]] == [("No", 1), ("Sì", 1)]


def test_raggruppamento_non_ammesso_ignorato(client, superuser, vista, dati):
    r = client.get("/core/aziende/", {"g": "telefono"})
    assert r.context["gruppo"] == "" and r.context["blocchi"][0]["etichetta"] is None


def test_gruppi_per_mese(db, monkeypatch):
    v = registry.per_modello(Lavoro)
    monkeypatch.setattr(v, "list_group_by", ["creato:mese"])
    for giorno in (datetime.datetime(2026, 9, 3, 23, 30), datetime.datetime(2026, 10, 1, 0, 30)):
        Lavoro.objects.filter(pk=Lavoro.objects.create(funzione="x").pk).update(creato=timezone.make_aware(giorno))
    _, info = gruppi.gruppi(v, Lavoro.objects.all(), "creato:mese")
    assert sorted(g["etichetta"] for g in info.values()) == ["ottobre 2026", "settembre 2026"]


def test_selettore_solo_lista(client, superuser, vista, dati):
    html = client.get("/core/aziende/", {"q": "A", "g": "provincia"}).content.decode()
    assert "ui-selettore" not in html          # nessun'altra vista dichiarata
