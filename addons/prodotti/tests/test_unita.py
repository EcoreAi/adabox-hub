"""Unità di misura: conversioni nella stessa categoria, unità di vendita e acquisto del prodotto, righe d'ordine con
quantità base e prezzo riportato, consegna e ricevimento nell'unità del prodotto, fattura differita e XML."""
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from prodotti import hooks
from prodotti.models import Prodotto, UnitaMisura, converti


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    hooks.unita_aggiuntive()
    azienda = Azienda.objects.get(pk=1)
    u = {x.simbolo: x for x in UnitaMisura.objects.all()}
    viti = Prodotto.objects.create(azienda=azienda, nome="Viti", unita=u["pz"], unita_vendita=u["dz"], prezzo_vendita=Decimal("0.50"),
                                   costo=Decimal("0.20"))
    return {"azienda": azienda, "u": u, "viti": viti}


def test_conversioni(s):
    u = s["u"]
    assert converti(Decimal(2), u["dz"], u["pz"]) == Decimal(24) and converti(Decimal(1500), u["g"], u["kg"]) == Decimal("1.5")
    assert converti(Decimal(3), u["h"], u["min"]) == Decimal("180.000")
    with pytest.raises(ValidationError):
        converti(Decimal(1), u["kg"], u["pz"])
    with pytest.raises(ValidationError):
        converti(Decimal(1), u["gg"], u["h"])                                   # «altro» non si converte
    p = Prodotto(azienda=s["azienda"], nome="X", unita=u["pz"], unita_vendita=u["kg"])
    with pytest.raises(ValidationError):
        p.full_clean()
    hooks.unita_aggiuntive()
    assert UnitaMisura.objects.filter(simbolo="dz").count() == 1                 # rieseguito: nessun doppione


def test_ordine_consegna_e_fattura(s):
    from fatturazione import fatturapa, operazioni as fatture
    from magazzino import operazioni
    from magazzino.models import Consegna, Magazzino, giacenza
    from vendite.models import OrdineVendita, RigaVendita
    from vendite.segnali import ordine_confermato
    cliente = Contatto.objects.create(azienda=s["azienda"], nome="Rossi Srl", cliente=True, partita_iva="12345678903")
    o = OrdineVendita.objects.create(azienda=s["azienda"], cliente=cliente)
    r = RigaVendita.objects.create(ordine=o, prodotto=s["viti"], quantita=2)              # 2 dozzine
    assert r.unita == s["u"]["dz"] and r.quantita_base == 24 and r.prezzo == Decimal("6.0000") and r.importo == Decimal("12.00")
    with pytest.raises(ValidationError):
        RigaVendita(ordine=o, prodotto=s["viti"], quantita=1, unita=s["u"]["kg"]).full_clean()
    Magazzino.objects.get_or_create(azienda=s["azienda"], nome="Sede", defaults={"predefinito": True})
    ordine_confermato.send(sender=OrdineVendita, ordine=o)
    c = Consegna.objects.get()
    assert c.righe.get().quantita == 24                                                 # la consegna è in pezzi
    operazioni.spedisci(c)
    assert giacenza(s["viti"]) == -24
    f = fatture.da_consegne([c])
    riga = f.righe.get()
    assert (riga.quantita, riga.unita.simbolo, riga.prezzo, riga.importo) == (Decimal(24), "pz", Decimal("0.5000"), Decimal("12.00"))
    OrdineVendita.objects.filter(pk=o.pk).update(stato="confermato")
    f.stato = "annullata"
    f.save(update_fields=["stato"])
    diretta = fatture.da_ordine(OrdineVendita.objects.get(pk=o.pk))
    rd = diretta.righe.get()
    assert rd.unita.simbolo == "dz" and rd.quantita == 2 and rd.importo == Decimal("12.00")


def test_acquisto_e_ricevimento(s):
    from acquisti.models import OrdineAcquisto, RigaAcquisto
    from magazzino.collegamenti import ricevimento_da_ordine
    from magazzino.models import Magazzino
    s["viti"].unita_acquisto = s["u"]["dz"]
    s["viti"].save()
    fornitore = Contatto.objects.create(azienda=s["azienda"], nome="Ferramenta", fornitore=True)
    Magazzino.objects.get_or_create(azienda=s["azienda"], nome="Sede", defaults={"predefinito": True})
    o = OrdineAcquisto.objects.create(azienda=s["azienda"], fornitore=fornitore)
    r = RigaAcquisto.objects.create(ordine=o, prodotto=s["viti"], quantita=10)
    assert r.unita.simbolo == "dz" and r.quantita_base == 120 and r.prezzo == Decimal("2.4000")
    ric = ricevimento_da_ordine(OrdineAcquisto, o)
    assert ric.righe.get().quantita == 120
