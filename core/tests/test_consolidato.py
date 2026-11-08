"""PLT-01: interrogazioni, grafici e KPI consolidati su più aziende dell'utente: ogni azienda con le sue regole, poi si
somma; le medie vengono da somme e conteggi; un'azienda che l'utente non ha non entra mai."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from contatti.models import Contatto
from core.models import Azienda
from core.viste import interroga


@pytest.fixture
def s(db):
    nord, sud, estranea = Azienda.objects.get(pk=1), Azienda.objects.create(nome="Sud"), Azienda.objects.create(nome="Estranea")
    u = User.objects.create_superuser("capo", "c@example.com", "x")
    u.profilo.aziende.set([nord, sud])
    u.profilo.azienda_predefinita = nord
    u.profilo.save()
    for az, fidi in ((nord, [100, 300]), (sud, [600]), (estranea, [9999])):
        for i, f in enumerate(fidi):
            Contatto.objects.create(azienda=az, nome=f"{az.nome} {i}", tipo="azienda" if i == 0 else "persona", fido=Decimal(f))
    request = interroga.richiesta_di(u, nord)
    return {"u": u, "nord": nord, "sud": sud, "estranea": estranea, "request": request,
            "vista": interroga.vista_per_nome("contatti.contatti", request)}


def test_solo_la_corrente_come_prima(s):
    r = interroga.aggrega(s["vista"], s["request"], misura="sum:fido")
    assert r["totale"] == 400 and "aziende" not in r


def test_tutte_le_mie_aziende(s):
    aziende = interroga.aziende_di(s["request"], "tutte")
    assert {a.pk for a in aziende} == {s["nord"].pk, s["sud"].pk}                     # l'estranea no
    r = interroga.aggrega(s["vista"], s["request"], "tipo", "sum:fido", aziende=aziende)
    assert r["totale"] == 1000 and {g["gruppo"]: g["valore"] for g in r["gruppi"]} == {"Azienda": 700, "Persona": 300}
    media = interroga.aggrega(s["vista"], s["request"], misura="avg:fido", aziende=aziende)
    assert media["totale"] == pytest.approx(333.33, abs=0.01)                          # (100+300+600)/3, non la media delle medie
    per_azienda = interroga.aggrega(s["vista"], s["request"], "azienda", "count", aziende=aziende)
    assert {g["gruppo"]: g["valore"] for g in per_azienda["gruppi"]} == {"Azienda principale" if s["nord"].nome == "Azienda principale" else s["nord"].nome: 2, "Sud": 1}


def test_id_non_consentiti_ignorati(s):
    assert interroga.aziende_di(s["request"], [s["estranea"].pk]) is None
    scelte = interroga.aziende_di(s["request"], [s["sud"].pk, s["estranea"].pk])
    assert [a.pk for a in scelte] == [s["sud"].pk]
    assert interroga.aggrega(s["vista"], s["request"], misura="sum:fido", aziende=scelte)["totale"] == 600


def test_grafico_e_kpi_consolidati(s):
    dati = interroga.calcola({"vista": "contatti.contatti", "per": "tipo", "misura": "count", "aziende": "tutte"}, s["request"])
    assert dati["totale"] == 3 and dict(dati["serie"]) == {"Azienda": 2, "Persona": 1}
    k = interroga.kpi({"vista": "contatti.contatti", "misura": "sum:fido", "aziende": "tutte"}, s["request"])
    assert k["valore"] == 1000


def test_costruttore_e_ada(client, s):
    client.force_login(s["u"])
    html = client.get("/grafici/costruttore/?vista=contatti.contatti&tipo=barre&per=tipo&aziende=tutte").content.decode()
    assert "Tutte le mie aziende (consolidato)" in html and "tutte le tue aziende" in html
    from ai.strumenti import Contesto
    from ai.strumenti.viste import aggrega_record
    ctx = Contesto(utente=s["u"], azienda=s["nord"])
    assert aggrega_record(ctx, "contatti.contatti", misura="sum:fido", aziende="tutte")["totale"] == 1000
