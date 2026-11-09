"""Lettura dei codici: ricerca per codice del prodotto o della confezione, quantità lette sul ricevimento (con prodotti
in più) e sulla consegna (senza), chiusura del documento, spostamento, permessi e pagine."""
import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from magazzino.models import Consegna, Magazzino, Ricevimento, RigaConsegna, RigaRicevimento, giacenza
from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)
from prodotti.models import Confezione, Prodotto


@pytest.fixture
def s(scena, client):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, corso = scena
    monitor.codice_barre = "8000000000017"
    monitor.save()
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", codice_barre="8000000000024")
    Confezione.objects.create(prodotto=cavo, nome="Scatola", quantita=10, codice_barre="8000000000031")
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    return {"azienda": azienda, "magazzino": magazzino, "cliente": cliente, "fornitore": fornitore, "monitor": monitor, "cavo": cavo,
            "corso": corso}


def test_codice(client, s):
    r = client.get("/magazzino/lettura/codice/?c=8000000000031").json()
    assert r == {"id": s["cavo"].pk, "nome": str(s["cavo"]), "pezzi": 10.0}
    assert client.get("/magazzino/lettura/codice/?c=8000000000017").json()["pezzi"] == 1.0
    assert client.get("/magazzino/lettura/codice/?c=999").status_code == 404


def test_ricevimento_letto_e_ricevuto(client, s):
    r = Ricevimento.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], fornitore=s["fornitore"])
    RigaRicevimento.objects.create(ricevimento=r, prodotto=s["monitor"], quantita=5)
    url = f"/magazzino/lettura/ricevimento/{r.pk}/"
    html = client.get(url).content.decode()
    assert "Ricevi" in client.get("/magazzino/lettura/").content.decode() and "Monitor" in html and "Salva e ricevi" in html
    risposta = client.post(url, {"letture": json.dumps({s["monitor"].pk: 4, s["cavo"].pk: 20}), "chiudi": "1"})
    assert risposta.status_code == 302
    r.refresh_from_db()
    assert r.stato == "fatto" and giacenza(s["monitor"]) == 4 and giacenza(s["cavo"]) == 20
    assert client.get(url).status_code == 302                                    # non è più in bozza


def test_consegna_con_quantita_diverse(client, s):
    c = Consegna.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], cliente=s["cliente"])
    RigaConsegna.objects.create(consegna=c, prodotto=s["monitor"], quantita=3)
    RigaConsegna.objects.create(consegna=c, prodotto=s["cavo"], quantita=10)
    url = f"/magazzino/lettura/consegna/{c.pk}/"
    client.post(url, {"letture": json.dumps({s["monitor"].pk: 2, s["corso"].pk: 1})})        # il servizio si ignora
    assert list(c.righe.order_by("pk").values_list("quantita", flat=True)) == [Decimal("2"), Decimal("10")]   # cavo non letto: resta
    altro = Prodotto.objects.create(azienda=s["azienda"], nome="Tastiera")
    client.post(url, {"letture": json.dumps({altro.pk: 1})})
    assert not c.righe.filter(prodotto=altro).exists()                                         # nella consegna non si aggiunge
    client.post(url, {"letture": json.dumps({s["monitor"].pk: 2}), "togli": "1"})
    assert list(c.righe.values_list("prodotto__nome", flat=True)) == ["Monitor"]
    client.post(url, {"letture": "rotto"})
    assert c.righe.count() == 1


def test_sposta(client, s):
    vetrina = Magazzino.objects.create(azienda=s["azienda"], nome="Vetrina")
    r = Ricevimento.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], fornitore=s["fornitore"])
    RigaRicevimento.objects.create(ricevimento=r, prodotto=s["cavo"], quantita=30)
    from magazzino import operazioni
    operazioni.ricevi(r)
    assert "Sposta" in client.get("/magazzino/lettura/sposta/").content.decode()
    client.post("/magazzino/lettura/sposta/", {"letture": json.dumps({s["cavo"].pk: 10}), "da": f"m{s['magazzino'].pk}", "a": f"m{vetrina.pk}"})
    assert giacenza(s["cavo"], vetrina) == 10 and giacenza(s["cavo"], s["magazzino"]) == 20


def test_permessi(client, s):
    from django.contrib.auth.models import Permission
    u = User.objects.create_user("vede", "v@x.it", "x")
    u.user_permissions.add(Permission.objects.get(codename="view_movimento"))
    client.force_login(u)
    c = Consegna.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], cliente=s["cliente"])
    assert client.get(f"/magazzino/lettura/consegna/{c.pk}/").status_code == 403
    assert client.get("/magazzino/lettura/sposta/").status_code == 403
    assert client.get("/magazzino/lettura/altro/1/").status_code == 403
