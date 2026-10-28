from decimal import Decimal
from pathlib import Path

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

import fiscale
import prodotti
from contatti.models import Contatto
from core import parametri
from core.models import Azienda
from magazzino import hooks, operazioni
from magazzino.models import Consegna, Magazzino, Movimento, Ricevimento, RigaConsegna, RigaRicevimento, giacenza
from prodotti.models import Prodotto


@pytest.fixture
def scena(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    from core.registry import manifest
    from core.registry.groups import crea_gruppi
    import magazzino
    crea_gruppi(manifest.leggi(Path(magazzino.__file__).parent))       # come fa l'installazione, prima dell'hook
    hooks.post_install(None)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    fornitore = Contatto.objects.create(azienda=azienda, nome="Grossista Spa", fornitore=True)
    monitor = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("200"), scorta_minima=5)
    corso = Prodotto.objects.create(azienda=azienda, nome="Corso", tipo="servizio")
    return azienda, Magazzino.objects.get(azienda=azienda), cliente, fornitore, monitor, corso


def test_magazzino_predefinito(scena):
    azienda, magazzino, *_ = scena
    assert magazzino.predefinito and Magazzino.predefinito_per(azienda) == magazzino


def test_ricevimento_e_consegna(scena):
    azienda, magazzino, cliente, fornitore, monitor, _ = scena
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=monitor, quantita=10)
    operazioni.ricevi(r)
    assert giacenza(monitor) == 10 and r.stato == "fatto"
    with pytest.raises(ValidationError):
        operazioni.ricevi(r)                                           # già ricevuto
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=monitor, quantita=4)
    operazioni.spedisci(c)
    assert giacenza(monitor, magazzino) == 6 and c.numero == f"DDT/{timezone.localdate().year}/0001"
    assert set(Movimento.objects.values_list("tipo", flat=True)) == {"carico", "scarico"}


def test_giacenza_negativa_vietata(scena):
    azienda, magazzino, cliente, _, monitor, _ = scena
    parametri.scrivi("magazzino.giacenza_negativa", False, azienda)
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=monitor, quantita=1)
    with pytest.raises(ValidationError, match="insufficiente"):
        operazioni.spedisci(c)
    assert c.stato == "bozza" and not Movimento.objects.exists()


def test_servizi_non_movimentabili(scena):
    azienda, magazzino, _, _, _, corso = scena
    with pytest.raises(ValidationError):
        Movimento(azienda=azienda, magazzino=magazzino, prodotto=corso, quantita=1).full_clean()


def test_rettifica_dalla_vista_e_movimenti_bloccati(client, superuser, scena):
    azienda, magazzino, _, _, monitor, _ = scena
    r = client.post("/magazzino/movimenti/nuovo/", {"prodotto": monitor.pk, "magazzino": magazzino.pk,
                                                    "quantita": "7", "causale": "Inventario"})
    m = Movimento.objects.get()
    assert r.status_code == 302 and m.tipo == "rettifica" and m.utente == superuser
    assert client.get(f"/magazzino/movimenti/{m.pk}/modifica/").status_code == 403


def test_pagina_giacenze_e_scorta(client, superuser, scena):
    azienda, magazzino, _, _, monitor, _ = scena
    Movimento.objects.create(azienda=azienda, magazzino=magazzino, prodotto=monitor, quantita=2)
    html = client.get("/magazzino/giacenze/").content.decode()
    assert "Monitor" in html and "sotto scorta" in html
    assert client.get("/magazzino/giacenze/", {"sotto_scorta": "1"}).context["righe"][0]["totale"] == 2
    schede = {s["slug"]: s for s in client.get("/dashboard/").context["schede"]}
    assert schede["magazzino"]["kpi"][0]["valore"] == 1


def test_bottone_spedisci_e_ddt(client, superuser, scena):
    azienda, magazzino, cliente, _, monitor, _ = scena
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=monitor, quantita=1)
    client.post(f"/magazzino/consegne/{c.pk}/bottone/spedisci/")
    c.refresh_from_db()
    assert c.stato == "fatto" and client.get(f"/magazzino/consegne/{c.pk}/modifica/").status_code == 403
    html = client.get(f"/magazzino/consegne/{c.pk}/stampa/0/", {"html": 1}).content.decode()
    assert "Documento di trasporto DDT/" in html and "Rossi Srl" in html


@pytest.mark.skipif(not apps.is_installed("vendite"), reason="serve vendite")
def test_ordine_confermato_crea_la_consegna(client, superuser, scena):
    from vendite.models import OrdineVendita, RigaVendita
    azienda, _, cliente, _, monitor, corso = scena
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente)
    RigaVendita.objects.create(ordine=o, prodotto=monitor, quantita=3)
    RigaVendita.objects.create(ordine=o, prodotto=corso, quantita=1)
    o.ricalcola()
    client.post(f"/vendite/ordini/{o.pk}/bottone/conferma/")
    c = Consegna.objects.get()
    assert c.cliente == cliente and c.riferimento.startswith("OV/")
    assert [(r.prodotto, r.quantita) for r in c.righe.all()] == [(monitor, Decimal("3.000"))]   # niente servizi
    assert f"/magazzino/consegne/{c.pk}/" in client.get(f"/vendite/ordini/{o.pk}/").content.decode()


def test_demo(scena):
    from prodotti import hooks as hp
    hp.demo(None)
    hooks.demo(None)
    hooks.demo(None)
    assert Movimento.objects.filter(causale="Inventario iniziale").count() == Prodotto.objects.filter(tipo="bene").count()


def test_demo_crea_consegne_e_ricevimenti_degli_ordini_confermati(scena):
    """Il ponte nei dati demo: in qualunque ordine si installino le app, gli ordini confermati hanno i documenti."""
    if not (apps.is_installed("vendite") and apps.is_installed("acquisti")):
        pytest.skip("servono vendite e acquisti")
    from acquisti import hooks as ha
    from magazzino import collegamenti
    from prodotti import hooks as hp
    from vendite import hooks as hv
    hp.demo(None)
    hv.demo(None)                                     # emette il segnale: consegne create subito
    ha.demo(None)
    assert Consegna.objects.count() == 2 and Ricevimento.objects.count() == 1
    Consegna.objects.all().delete()                   # come se il magazzino fosse arrivato dopo
    hooks.demo(None)
    assert Consegna.objects.count() == 2 and collegamenti.recupera_ordini(scena[0]) == 0
