"""Operazioni tra aziende del gruppo: la vendita confermata a un'azienda della stessa installazione crea l'ordine al
fornitore speculare, la fattura si collega da sola, l'annullamento della vendita annulla l'ordine."""
from decimal import Decimal

from acquisti import riscontro
from acquisti.models import FatturaOrdine, OrdineAcquisto, RegolaGruppo
from acquisti.tests.test_riscontro import _fattura, scena  # noqa: F401
from contatti.models import Contatto
from core.models import Azienda
from prodotti.models import Prodotto
from vendite import operazioni as vendite
from vendite.models import OrdineVendita, RigaVendita


def _gruppo(scena):  # noqa: F811
    madre, _, toner = scena
    Azienda.objects.filter(pk=madre.pk).update(partita_iva="11111111111")
    madre.refresh_from_db()
    figlia = Azienda.objects.create(nome="Figlia Srl", partita_iva="22222222222")
    Prodotto.objects.filter(pk=toner.pk).update(codice="TON")
    toner_figlia = Prodotto.objects.create(azienda=figlia, nome="Toner", codice="TON")
    cliente = Contatto.objects.create(azienda=madre, nome="Figlia Srl", cliente=True, partita_iva="22222222222")
    o = OrdineVendita.objects.create(azienda=madre, cliente=cliente)
    RigaVendita.objects.create(ordine=o, prodotto_id=toner.pk, descrizione="Toner", quantita=3, prezzo=Decimal("64"))
    RigaVendita.objects.create(ordine=o, descrizione="Assistenza", quantita=1, prezzo=Decimal("100"))
    o.ricalcola()
    return madre, figlia, toner_figlia, o


def test_ordine_speculare_e_fattura_collegata(scena):  # noqa: F811
    madre, figlia, toner_figlia, o = _gruppo(scena)
    vendite.conferma(o)
    assert not OrdineAcquisto.objects.filter(azienda=figlia).exists()            # senza regola niente
    o2 = OrdineVendita.objects.create(azienda=madre, cliente=o.cliente)
    RigaVendita.objects.create(ordine=o2, descrizione="Toner", quantita=3, prezzo=Decimal("64"), prodotto=o.righe.first().prodotto)
    o2.ricalcola()
    RegolaGruppo.objects.create(venditrice=madre, acquirente=figlia)
    vendite.conferma(o2)
    oa = OrdineAcquisto.objects.get(azienda=figlia)
    assert oa.stato == OrdineAcquisto.CONFERMATO and oa.ordine_gruppo_id == o2.pk
    assert oa.fornitore.partita_iva == "11111111111" and oa.fornitore.fornitore and oa.fornitore.azienda == figlia
    assert oa.righe.get().prodotto == toner_figlia and oa.imponibile == Decimal("192.00")
    o2.refresh_from_db()
    assert o2.riferimento_cliente == oa.numero                                   # la fattura lo porterà in DatiOrdineAcquisto
    # la fattura della madre arriva alla figlia dallo SDI e si collega da sola
    f = _fattura(figlia, oa.fornitore, Decimal("192"))
    riscontro.fattura_ricevuta(None, f, {"ordini": [o2.riferimento_cliente]})
    assert FatturaOrdine.objects.filter(ordine=oa, fattura_id=f.pk).exists()
    # di nuovo la conferma non duplica
    from acquisti import gruppo
    assert gruppo.da_vendita(None, o2) is None and OrdineAcquisto.objects.filter(azienda=figlia).count() == 1


def test_bozza_e_annullamento(scena):  # noqa: F811
    madre, figlia, _, o = _gruppo(scena)
    RegolaGruppo.objects.create(venditrice=madre, acquirente=figlia, conferma=False)
    vendite.conferma(o)
    oa = OrdineAcquisto.objects.get(azienda=figlia)
    assert oa.stato == OrdineAcquisto.BOZZA and oa.righe.count() == 2
    from vendite.segnali import ordine_annullato
    ordine_annullato.send(sender=OrdineVendita, ordine=o, utente=None)
    oa.refresh_from_db()
    assert oa.stato == OrdineAcquisto.ANNULLATO


def test_pagina_regole(scena, client):  # noqa: F811
    from django.contrib.auth.models import User
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert client.get("/acquisti/regole-gruppo/").status_code == 200
    assert client.get("/acquisti/regole-gruppo/nuovo/").status_code == 200
