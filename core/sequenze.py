"""Sequenze: numeri progressivi senza buchi né doppioni (select_for_update), dichiarate nel manifest."""
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Azienda, Sequenza
from .registry import modules


def definizioni():
    return {v["codice"]: v for m in modules.manifests_attivi().values() for v in m.sequences}


def formatta(formato, numero, data=None):
    data = data or timezone.localdate()
    return formato.format(numero=numero, anno=data.year, mese=data.month, giorno=data.day)


def crea(voci, aziende=None):
    """Crea (o aggiorna formato e azzeramento) le sequenze per ogni azienda; il numero non si tocca."""
    aziende = list(Azienda.objects.all()) if aziende is None else aziende
    for v in voci:
        for azienda in aziende:
            Sequenza.objects.update_or_create(codice=v["codice"], azienda=azienda, defaults={
                "formato": v["formato"], "azzera": v.get("azzera", Sequenza.MAI)})


def _riga(codice, azienda):
    qs = Sequenza.objects.select_for_update().filter(codice=codice, azienda=azienda)
    if (seq := qs.first()) is not None:
        return seq
    voce = definizioni().get(codice)                      # creata al primo uso se manca
    if voce is None:
        raise KeyError(f"sequenza {codice!r} non dichiarata da nessun modulo installato")
    try:
        with transaction.atomic():
            Sequenza.objects.create(codice=codice, azienda=azienda, formato=voce["formato"],
                                    azzera=voce.get("azzera", Sequenza.MAI))
    except IntegrityError:
        pass                                              # creata nel frattempo da un'altra richiesta
    return qs.get()


def prossimo(codice, azienda=None):
    """Il prossimo numero formattato. Va chiamato dentro la transazione che salva il record."""
    with transaction.atomic():
        seq = _riga(codice, azienda)
        oggi = timezone.localdate()
        if seq.azzera == Sequenza.ANNO and seq.anno != oggi.year:
            seq.prossimo, seq.anno = 1, oggi.year
        numero = seq.prossimo
        seq.prossimo += 1
        seq.save(update_fields=["prossimo", "anno"])
    return formatta(seq.formato, numero, oggi)
