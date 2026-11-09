"""Triangolazione: le righe «spedisce il fornitore» non vanno in consegna, diventano una richiesta al fornitore del
listino con il cliente come destinatario, senza ricevimento; spedito segnato sull'ordine al fornitore."""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from acquisti import operazioni, triangolazione
from acquisti.models import OrdineAcquisto, VoceListino
from acquisti.tests.test_riscontro import scena  # noqa: F401
from contatti.models import Contatto
from magazzino.models import Consegna, Magazzino, Ricevimento
from prodotti.models import Prodotto
from vendite import operazioni as vendite
from vendite.models import OrdineVendita, RigaVendita


def test_triangolazione(scena):  # noqa: F811
    azienda, fornitore, toner = scena
    Magazzino.objects.get_or_create(azienda=azienda, nome="Sede", defaults={"predefinito": True})
    stampante = Prodotto.objects.create(azienda=azienda, nome="Stampante", prezzo_vendita=Decimal("500"))
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=stampante, prezzo=Decimal("300"))
    cliente = Contatto.objects.create(azienda=azienda, nome="Bianchi Srl", cliente=True, indirizzo="Via Roma 1", cap="00100", citta="Roma")
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente)
    RigaVendita.objects.create(ordine=o, prodotto=toner, quantita=2)
    RigaVendita.objects.create(ordine=o, prodotto=stampante, quantita=1, diretta=True)
    o.ricalcola()
    vendite.conferma(o)
    consegna = Consegna.objects.get()
    assert list(consegna.righe.values_list("prodotto__nome", flat=True)) == ["Toner"]          # la stampante non passa dal magazzino
    oa = OrdineAcquisto.objects.get(consegna_a=cliente)
    assert oa.fornitore == fornitore and oa.ordine_vendita_id == o.pk and "Via Roma 1" in oa.indirizzo_consegna
    assert oa.righe.get().prodotto == stampante
    with pytest.raises(ValidationError):
        triangolazione.segna_spedito(oa)                                                      # prima va confermato
    operazioni.conferma(oa)
    oa.refresh_from_db()
    assert not Ricevimento.objects.filter(origine_id=oa.pk).exists()                          # niente ricevimento
    triangolazione.segna_spedito(oa)
    assert oa.spedito_il is not None
