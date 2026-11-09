"""Garanzia dalla consegna e flusso della riparazione: preventivo, approvazione, lavorazione, ricambi scaricati,
riconsegna, fattura (niente fattura se in garanzia)."""
import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import chatter, sequenze

from .models import GaranziaProdotto, Riparazione


def _piu_mesi(data, mesi):
    m = data.month - 1 + mesi
    anno, mese = data.year + m // 12, m % 12 + 1
    import calendar
    return data.replace(year=anno, month=mese, day=min(data.day, calendar.monthrange(anno, mese)[1]))


def garanzia(azienda, prodotto=None, seriale="", cliente=None):
    """{consegnato_il, fino_al, attiva, fornitore_fino_al, consegna} dalla consegna del seriale (o, senza seriale,
    dall'ultima consegna del prodotto al cliente). None se non si trova la consegna o il prodotto non ha garanzia."""
    from magazzino.models import Consegna, Lotto, Movimento
    ct = ContentType.objects.get_for_model(Consegna)
    movimenti = Movimento.objects.filter(azienda=azienda, content_type=ct, quantita__lt=0)
    if seriale:
        lotto = Lotto.objects.filter(azienda=azienda, codice=seriale).select_related("prodotto").first()
        if lotto is None:
            return None
        prodotto = prodotto or lotto.prodotto
        movimenti = movimenti.filter(lotto=lotto)
    elif prodotto is not None:
        movimenti = movimenti.filter(prodotto=prodotto)
    else:
        return None
    if cliente is not None and not seriale:
        movimenti = movimenti.filter(object_id__in=Consegna.objects.filter(cliente=cliente).values_list("pk", flat=True))
    m = movimenti.order_by("-data").first()
    termini = GaranziaProdotto.objects.filter(prodotto=prodotto).first() if prodotto else None
    if m is None or termini is None:
        return None
    consegna = Consegna.objects.filter(pk=m.object_id).first()
    data = consegna.data if consegna else timezone.localtime(m.data).date()
    fino = _piu_mesi(data, termini.mesi)
    return {"consegnato_il": data, "fino_al": fino, "attiva": timezone.localdate() <= fino, "consegna": consegna, "prodotto": prodotto,
            "fornitore_fino_al": _piu_mesi(data, termini.mesi_fornitore) if termini.mesi_fornitore else None, "condizioni": termini.condizioni}


def accetta(riparazione):
    """All'ingresso: numero e garanzia proposta dalla consegna."""
    if not riparazione.numero:
        riparazione.numero = sequenze.prossimo("riparazioni.riparazione", riparazione.azienda)
    g = garanzia(riparazione.azienda, riparazione.prodotto, riparazione.seriale, riparazione.cliente)
    if g:
        riparazione.in_garanzia, riparazione.garanzia_fino_al = g["attiva"], g["fino_al"]
        riparazione.recupero_fornitore = bool(g["attiva"] and g["fornitore_fino_al"] and timezone.localdate() <= g["fornitore_fino_al"])
    riparazione.save(update_fields=["numero", "in_garanzia", "garanzia_fino_al", "recupero_fornitore"])


def _passa(r, da, a, utente, testo):
    if r.stato not in da:
        raise ValidationError(f"Non si può: la riparazione è «{r.get_stato_display().lower()}».")
    r.stato = a
    r.save(update_fields=["stato"])
    chatter.scrivi(r, utente, testo, tipo="nota")


def preventivo(r, utente=None):
    if r.in_garanzia:
        return _passa(r, [Riparazione.RICEVUTA], Riparazione.APPROVATA, utente, "In garanzia: nessun preventivo, si ripara.")
    _passa(r, [Riparazione.RICEVUTA], Riparazione.PREVENTIVO, utente, f"Preventivo di {r.totale:.2f} € comunicato al cliente.")


def approva(r, utente=None):
    _passa(r, [Riparazione.PREVENTIVO], Riparazione.APPROVATA, utente, "Il cliente approva il preventivo.")


def rifiuta(r, utente=None):
    _passa(r, [Riparazione.PREVENTIVO], Riparazione.RIFIUTATA, utente, "Il cliente rifiuta il preventivo: il bene torna com'è.")


def avvia(r, utente=None):
    _passa(r, [Riparazione.APPROVATA], Riparazione.LAVORAZIONE, utente, "Riparazione in lavorazione.")


@transaction.atomic
def pronta(r, utente=None):
    """Lavoro finito: i ricambi escono dal magazzino."""
    from magazzino import lotti
    from magazzino.models import Movimento
    if r.stato != Riparazione.LAVORAZIONE:
        raise ValidationError("Prima avvia la lavorazione.")
    ct = ContentType.objects.get_for_model(Riparazione)
    for riga in r.righe.select_related("prodotto").filter(scaricato=False):
        finta = type("R", (), {"quantita": riga.quantita, "lotti": "", "ubicazione": None})()
        for lotto, q in lotti.per_uscita(finta, riga.prodotto, r.magazzino):
            Movimento.objects.create(azienda=r.azienda, prodotto=riga.prodotto, magazzino=r.magazzino, lotto=lotto, quantita=-q,
                                     tipo=Movimento.SCARICO, causale=f"Ricambio per {r.numero}", utente=utente, content_type=ct, object_id=r.pk)
        riga.scaricato = True
        riga.save(update_fields=["scaricato"])
    _passa(r, [Riparazione.LAVORAZIONE], Riparazione.PRONTA, utente, "Riparazione pronta: il cliente può ritirare.")


def riconsegna(r, utente=None):
    if r.stato not in (Riparazione.PRONTA, Riparazione.RIFIUTATA):
        raise ValidationError("Si riconsegna una riparazione pronta o con il preventivo rifiutato.")
    r.stato, r.riconsegnata_il = Riparazione.RICONSEGNATA, timezone.localdate()
    r.save(update_fields=["stato", "riconsegnata_il"])
    chatter.scrivi(r, utente, f"Bene riconsegnato al cliente il {r.riconsegnata_il:%d/%m/%Y}.", tipo="nota")


@transaction.atomic
def fattura(r, utente=None):
    from fatturazione.models import Fattura, RigaFattura
    if r.in_garanzia:
        raise ValidationError("In garanzia: non si fattura.")
    if r.stato not in (Riparazione.PRONTA, Riparazione.RICONSEGNATA):
        raise ValidationError("Si fattura una riparazione pronta o riconsegnata.")
    if r.fattura_id and Fattura.objects.filter(pk=r.fattura_id).exclude(stato=Fattura.ANNULLATA).exists():
        raise ValidationError("La riparazione è già fatturata.")
    f = Fattura.objects.create(azienda=r.azienda, cliente=r.cliente, causale=f"Riparazione {r.numero}"[:200])
    for riga in r.righe.select_related("prodotto"):
        RigaFattura.objects.create(fattura=f, prodotto=riga.prodotto, quantita=riga.quantita, unita=riga.prodotto.unita,
                                   prezzo=riga.prezzo if riga.prezzo is not None else riga.prodotto.prezzo_vendita)
    if r.ore:
        RigaFattura.objects.create(fattura=f, descrizione=f"Manodopera riparazione {r.numero} ({r.ore:g} ore)", quantita=r.ore, prezzo=r.tariffa)
    f.ricalcola()
    r.fattura_id = f.pk
    r.save(update_fields=["fattura_id"])
    return f
