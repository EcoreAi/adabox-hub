import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command

import crm
from contatti.models import Contatto
from core import chatter, parametri
from core.models import Azienda
from core.registry import manifest
from core.registry.groups import crea_gruppi
from crm.models import FaseCrm, Opportunita

CARTELLA = Path(crm.__file__).parent


@pytest.fixture
def dati(db):
    call_command("loaddata", str(CARTELLA / "data" / "iniziali.json"), verbosity=0)
    crea_gruppi(manifest.leggi(CARTELLA))


@pytest.fixture
def commerciale(dati, client):
    u = User.objects.create_user("sara", "sara@example.com", "x")
    u.groups.add(Group.objects.get(name="CRM / Commerciale"))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    return u


def _fase(nome):
    return FaseCrm.objects.get(nome=nome)


def _opp(**kw):
    return Opportunita.objects.create(azienda=Azienda.objects.get(pk=1), **{"titolo": "Offerta", **kw})


def test_fase_iniziale_e_probabilita(dati):
    o = _opp()
    assert o.fase.nome == "Nuova" and o.stato == "aperta"
    o.fase = _fase("Proposta")
    o.save()
    assert o.probabilita == 60


def test_fase_vinta_e_ritorno(dati):
    o = _opp()
    o.fase = _fase("Vinta")
    o.save()
    assert (o.stato, o.probabilita) == ("vinta", 100) and o.chiusa_il
    o.fase = _fase("Negoziazione")
    o.save()
    assert o.stato == "aperta" and o.chiusa_il is None and o.probabilita == 80


def test_parametro_disattiva_la_probabilita(dati):
    parametri.scrivi("crm.probabilita_dalla_fase", False)
    o = _opp(probabilita=42)
    o.fase = _fase("Proposta")
    o.save()
    assert o.probabilita == 42


def test_kanban_sposta_nella_fase_vinta(client, commerciale):
    o = _opp()
    r = client.post(f"/crm/opportunita/{o.pk}/sposta/", {"valore": str(_fase("Vinta").pk)}, HTTP_HX_REQUEST="true")
    assert r.status_code == 204
    o.refresh_from_db()
    assert (o.stato, o.probabilita) == ("vinta", 100)                  # update_fields esteso dal save
    assert any(c["campo"] == "fase" for c in chatter.messaggi_di(o).first().modifiche)


def test_bottoni(client, commerciale):
    o = _opp(nome_contatto="Lead Srl", email="lead@srl.it")
    client.post(f"/crm/opportunita/{o.pk}/bottone/crea_contatto/")
    o.refresh_from_db()
    assert o.contatto.nome == "Lead Srl" and o.contatto.email == "lead@srl.it" and o.contatto.cliente
    client.post(f"/crm/opportunita/{o.pk}/bottone/segna_persa/")
    o.refresh_from_db()
    assert (o.stato, o.probabilita) == ("persa", 0)
    client.post(f"/crm/opportunita/{o.pk}/bottone/riapri/")
    o.refresh_from_db()
    assert o.stato == "aperta"
    client.post(f"/crm/opportunita/{o.pk}/bottone/segna_vinta/")
    o.refresh_from_db()
    assert o.stato == "vinta" and o.fase.vinta


def test_assegna_a_me_e_totali(client, commerciale):
    a, b = _opp(titolo="A", valore_atteso=Decimal("1000")), _opp(titolo="B", valore_atteso=Decimal("250.50"))
    client.post("/crm/opportunita/azione/assegna_a_me/", {"pk": [a.pk, b.pk]})
    assert set(Opportunita.objects.values_list("commerciale", flat=True)) == {commerciale.pk}
    r = client.get("/crm/opportunita/")
    assert "1.250,50" in r.content.decode()


def test_viste(client, commerciale):
    _opp(valore_atteso=Decimal("500"))
    for url in ("/crm/opportunita/kanban/", "/crm/opportunita/grafico/?misura=sum:valore_atteso",
                "/crm/opportunita/calendario/"):
        assert client.get(url).status_code == 200, url


def test_contatti_di_altre_aziende_non_selezionabili(client, commerciale):
    zeta = Azienda.objects.create(nome="Zeta")
    estraneo = Contatto.objects.create(azienda=zeta, nome="Estraneo")
    mio = Contatto.objects.create(azienda=Azienda.objects.get(pk=1), nome="Mio")
    scelte = list(client.get("/crm/opportunita/nuovo/").context["form"].fields["contatto"].queryset)
    assert mio in scelte and estraneo not in scelte


def test_demo_coerente():
    demo = json.loads((CARTELLA / "data" / "demo.json").read_text())
    assert len(demo) == 6 and all(r["fields"]["contatto"] is None for r in demo)
