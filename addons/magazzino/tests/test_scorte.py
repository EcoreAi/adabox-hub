"""Scorte per magazzino e previsto: la pagina Giacenze mostra impegnato, in arrivo e previsto; il riordino guarda il
singolo magazzino dove c'è una scorta per magazzino e crea la richiesta con il magazzino nella riga."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from acquisti import riordino
from magazzino import operazioni
from magazzino.models import Consegna, Magazzino, Ricevimento, RigaConsegna, RigaRicevimento, ScortaMagazzino
from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)


@pytest.fixture
def s(scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, corso = scena
    negozio = Magazzino.objects.create(azienda=azienda, nome="Negozio")
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=monitor, quantita=20)
    operazioni.ricevi(r)
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=monitor, quantita=4)
    arrivo = Ricevimento.objects.create(azienda=azienda, magazzino=negozio, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=arrivo, prodotto=monitor, quantita=1)
    return {"azienda": azienda, "magazzino": magazzino, "negozio": negozio, "monitor": monitor, "fornitore": fornitore}


def test_giacenze_con_previsto(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get("/magazzino/giacenze/").content.decode()
    assert "Previsto" in html and "Impegnato" in html
    from magazzino.pagine import situazione
    richiesta = type("R", (), {"user": User.objects.get(username="root"), "azienda": s["azienda"]})()
    _, righe = situazione(richiesta)
    r = next(x for x in righe if x["prodotto"] == s["monitor"])
    assert (r["totale"], r["impegnato"], r["in_arrivo"], r["previsto"]) == (20, 4, 1, 17)
    ScortaMagazzino.objects.create(azienda=s["azienda"], magazzino=s["negozio"], prodotto=s["monitor"], punto_riordino=3, scorta_obiettivo=5)
    _, righe = situazione(richiesta, solo_sotto_scorta=True)
    assert righe[0]["sotto_magazzino"] == ["Negozio"]                  # nel negozio: 0 + 1 in arrivo < 3


def test_riordino_per_magazzino(client, s):
    ScortaMagazzino.objects.create(azienda=s["azienda"], magazzino=s["negozio"], prodotto=s["monitor"], punto_riordino=3, scorta_obiettivo=5)
    ScortaMagazzino.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], prodotto=s["monitor"], punto_riordino=10, scorta_obiettivo=30)
    voci = riordino.proposte(s["azienda"])
    assert [(v["magazzino"].nome, v["previsto"], v["quantita"]) for v in voci] == [("Negozio", Decimal(1), Decimal(4))]   # la sede ne ha 16
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert "in Negozio" in client.get("/acquisti/riordino/").content.decode()
    voci[0]["fornitore"] = s["fornitore"]
    ordine, = riordino.crea_richieste(s["azienda"], voci)
    assert "per Negozio" in ordine.righe.get().descrizione
