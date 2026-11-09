"""Pagella dei fornitori: prezzo netto pagato rispetto al proprio listino e al più basso degli altri fornitori."""
import datetime
from decimal import Decimal

from acquisti import valutazione
from acquisti.models import VoceListino
from acquisti.tests.test_riscontro import _confermato, scena  # noqa: F401
from contatti.models import Contatto

OGGI = datetime.date.today()


def test_prezzi(scena):  # noqa: F811
    azienda, fornitore, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("10"))
    altro = Contatto.objects.create(azienda=azienda, nome="Concorrente", fornitore=True)
    VoceListino.objects.create(azienda=azienda, fornitore=altro, prodotto=toner, prezzo=Decimal("8"))
    o = _confermato(azienda, fornitore, toner)
    o.righe.update(prezzo=Decimal("11"))                                     # pagato 11 invece di 10 (e 8 dall'altro)
    riga, = valutazione.schede(azienda, OGGI - datetime.timedelta(days=1), OGGI)
    assert riga["vs_listino"] == Decimal("10.0") and riga["vs_migliore"] == Decimal("37.5")
