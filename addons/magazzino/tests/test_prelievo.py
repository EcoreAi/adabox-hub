"""Prelievo: giro ordinato per ubicazione con kit esplosi, prelevato e colli confermati, resto in una nuova consegna,
stampe della lista e della distinta colli."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from magazzino import operazioni, prelievo
from magazzino.models import Consegna, Ricevimento, RigaConsegna, RigaRicevimento, Ubicazione
from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)
from prodotti.models import ComponenteKit, Prodotto


@pytest.fixture
def s(scena, client):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, corso = scena
    a1 = Ubicazione.objects.create(azienda=azienda, magazzino=magazzino, codice="A-01")
    b2 = Ubicazione.objects.create(azienda=azienda, magazzino=magazzino, codice="B-02")
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo")
    kit = Prodotto.objects.create(azienda=azienda, nome="Postazione", kit=True)
    ComponenteKit.objects.create(kit=kit, componente=monitor, quantita=1)
    ComponenteKit.objects.create(kit=kit, componente=cavo, quantita=2)
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=monitor, quantita=10, ubicazione=b2)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=cavo, quantita=20, ubicazione=a1)
    operazioni.ricevi(r)
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=monitor, quantita=3)
    RigaConsegna.objects.create(consegna=c, prodotto=cavo, quantita=4)
    RigaConsegna.objects.create(consegna=c, prodotto=kit, quantita=1)
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    return {"c": c, "monitor": monitor, "cavo": cavo, "kit": kit}


def test_giro_per_ubicazione(s):
    voci = prelievo.giro(s["c"])
    assert [v["riga"].prodotto.nome for v in voci] == ["Cavo", "Postazione", "Monitor"]        # A-01 prima di B-02
    kit = voci[1]
    assert [(p["prodotto"].nome, p["quantita"], p["ubicazione"].codice) for p in kit["parti"]] == [
        ("Monitor", Decimal(1), "B-02"), ("Cavo", Decimal(2), "A-01")]


def test_conferma_con_colli_e_resto(client, s):
    c = s["c"]
    righe = {r.prodotto.nome: r for r in c.righe.select_related("prodotto")}
    url = f"/magazzino/consegna/{c.pk}/prelievo/"
    assert "Conferma: merce pronta" in client.get(url).content.decode()
    r = client.post(url, {f"p_{righe['Monitor'].pk}": "2", f"k_{righe['Monitor'].pk}": "1", f"p_{righe['Cavo'].pk}": "4",
                          f"k_{righe['Cavo'].pk}": "2", f"p_{righe['Postazione'].pk}": "1", f"k_{righe['Postazione'].pk}": "2",
                          "resto": "dopo"})
    assert r.status_code == 302
    c.refresh_from_db()
    assert c.stato == "pronto" and c.colli == 2 and c.righe.get(prodotto=s["monitor"]).quantita == 2
    residuo = Consegna.objects.exclude(pk=c.pk).get()
    assert list(residuo.righe.values_list("prodotto__nome", "quantita")) == [("Monitor", Decimal("1"))]
    colli = client.get(url + "?stampa=colli").content.decode()
    assert "Collo 1 di 2" in colli and "Collo 2 di 2" in colli
    assert "Lista di prelievo" in client.get(url + "?stampa=lista").content.decode()
    assert client.post(url, {f"p_{righe['Monitor'].pk}": "9"}).status_code == 302
    assert c.righe.get(prodotto=s["monitor"]).quantita == 2                                    # oltre il previsto: rifiutato
