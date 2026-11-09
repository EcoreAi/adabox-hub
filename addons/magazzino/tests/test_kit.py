"""Confezioni e kit: il kit esce come componenti, disponibilità, controlli, colli dalle confezioni, codice a barre
della confezione, scheda prodotto con le righe."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from core import parametri
from magazzino import operazioni
from magazzino.models import Consegna, Movimento, Ricevimento, RigaConsegna, RigaRicevimento, giacenza
from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)
from prodotti.models import ComponenteKit, Confezione, Prodotto, da_codice


def _carica(azienda, magazzino, fornitore, *righe):
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    for prodotto, q in righe:
        RigaRicevimento.objects.create(ricevimento=r, prodotto=prodotto, quantita=q)
    operazioni.ricevi(r)


@pytest.fixture
def kit(scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, corso = scena
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo HDMI")
    postazione = Prodotto.objects.create(azienda=azienda, nome="Postazione", kit=True, prezzo_vendita=Decimal("450"))
    ComponenteKit.objects.create(kit=postazione, componente=monitor, quantita=2)
    ComponenteKit.objects.create(kit=postazione, componente=cavo, quantita=2)
    _carica(azienda, magazzino, fornitore, (monitor, 5), (cavo, 10))
    return {"scena": scena, "cavo": cavo, "postazione": postazione}


def test_il_kit_esce_come_componenti(kit):
    azienda, magazzino, cliente, fornitore, monitor, _ = kit["scena"]
    assert operazioni.disponibili_kit(kit["postazione"]) == 2                 # 5 monitor / 2 per kit
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=kit["postazione"], quantita=2)
    operazioni.spedisci(c)
    assert giacenza(monitor) == 1 and giacenza(kit["cavo"]) == 6 and giacenza(kit["postazione"]) == 0
    assert not Movimento.objects.filter(prodotto=kit["postazione"]).exists()
    assert "kit Postazione" in Movimento.objects.filter(prodotto=monitor, tipo="scarico").get().causale
    assert operazioni.disponibili_kit(kit["postazione"]) == 0


def test_disponibilita_dei_componenti_e_ricevimento(kit):
    azienda, magazzino, cliente, fornitore, *_ = kit["scena"]
    parametri.scrivi("magazzino.giacenza_negativa", False, azienda)
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=kit["postazione"], quantita=3)       # servono 6 monitor
    with pytest.raises(ValidationError, match="Monitor"):
        operazioni.spedisci(c)
    with pytest.raises(ValidationError, match="Un kit non ha giacenza"):
        _carica(azienda, magazzino, fornitore, (kit["postazione"], 1))


def test_controlli_dei_componenti(kit):
    azienda, _, _, _, monitor, corso = kit["scena"]
    with pytest.raises(ValidationError):
        ComponenteKit(kit=kit["postazione"], componente=kit["postazione"], quantita=1).full_clean()
    with pytest.raises(ValidationError):
        ComponenteKit(kit=kit["postazione"], componente=corso, quantita=1).full_clean()      # servizio
    altro = Prodotto.objects.create(azienda=azienda, nome="Doppia", kit=True)
    with pytest.raises(ValidationError):
        ComponenteKit(kit=altro, componente=kit["postazione"], quantita=1).full_clean()      # kit nel kit
    vuoto = Prodotto.objects.create(azienda=azienda, nome="Kit vuoto", kit=True)
    assert vuoto.esploso(3) == [(vuoto, Decimal(3))]


def test_confezioni_colli_e_codice(kit):
    azienda, magazzino, cliente, _, monitor, _ = kit["scena"]
    Confezione.objects.create(prodotto=kit["cavo"], nome="Busta", quantita=1, peso=Decimal("0.2"))
    Confezione.objects.create(prodotto=kit["cavo"], nome="Scatola", quantita=4, codice_barre="8001234567890", peso=Decimal("1"))
    assert da_codice(azienda, "8001234567890") == (kit["cavo"], Decimal(4))
    assert da_codice(azienda, "nessuno") is None
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=kit["cavo"], quantita=9)                   # 3 scatole da 4
    assert operazioni.colli_suggeriti(c) == (3, Decimal("3.000"))
    operazioni.spedisci(c)
    c.refresh_from_db()
    assert c.colli == 3 and c.peso == Decimal("3.00")
    d = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente, colli=2)
    RigaConsegna.objects.create(consegna=d, prodotto=kit["cavo"], quantita=9)
    operazioni.spedisci(d)
    d.refresh_from_db()
    assert d.colli == 2                                                       # scritti a mano: restano


def test_scheda_prodotto(client, kit):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get(f"/prodotti/prodotti/{kit['postazione'].pk}/").content.decode()
    assert "Componenti del kit" in html and "se ne fanno" in html and "Cavo HDMI" in html
    assert "Confezioni" in client.get(f"/prodotti/prodotti/{kit['cavo'].pk}/modifica/").content.decode()


def test_componenti_dal_form(client, kit):
    azienda, _, _, _, monitor, _ = kit["scena"]
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    p = kit["postazione"]
    dati = {"nome": p.nome, "tipo": "bene", "unita": p.unita_id, "prezzo_vendita": "450", "costo": "0", "aliquota_iva": p.aliquota_iva_id,
            "scorta_minima": "0", "kit": "on", "attivo": "on",
            "righe0-TOTAL_FORMS": "1", "righe0-INITIAL_FORMS": "0", "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000",
            "righe0-0-nome": "Scatola", "righe0-0-quantita": "1", "righe0-0-codice_barre": "", "righe0-0-peso": "12"}
    componenti = list(p.componenti.order_by("pk"))
    dati.update({"righe1-TOTAL_FORMS": "2", "righe1-INITIAL_FORMS": "2", "righe1-MIN_NUM_FORMS": "0", "righe1-MAX_NUM_FORMS": "1000"})
    for i, c in enumerate(componenti):
        dati.update({f"righe1-{i}-id": c.pk, f"righe1-{i}-kit": p.pk, f"righe1-{i}-componente": c.componente_id,
                     f"righe1-{i}-quantita": "3" if i == 0 else "2"})
    r = client.post(f"/prodotti/prodotti/{p.pk}/modifica/", dati)
    assert r.status_code == 302, r.content.decode()[:500]
    assert p.componenti.get(componente=monitor).quantita == 3 and p.confezioni.get().nome == "Scatola"
