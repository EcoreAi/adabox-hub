"""Resi dei clienti: dal DDT al rientro della merce e alla nota di credito con le sole righe rese."""
from decimal import Decimal

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import sequenze

from . import costi, lotti
from .models import Movimento, Reso, RigaReso


def numera(reso):
    if not reso.numero:
        reso.numero = sequenze.prossimo("magazzino.reso", reso.azienda)
        reso.save(update_fields=["numero"])


def fattura_della_consegna(consegna):
    """La fattura che cita il DDT (differita) o, in mancanza, quella dell'ordine da cui viene la consegna."""
    if consegna is None or not apps.is_installed("fatturazione"):
        return None
    from fatturazione.models import Fattura, RiferimentoDDT
    if consegna.numero:
        rif = (RiferimentoDDT.objects.filter(numero=consegna.numero, data=consegna.data, fattura__azienda=consegna.azienda,
                                             fattura__stato=Fattura.EMESSA).select_related("fattura").first())
        if rif:
            return rif.fattura
    if consegna.origine_tipo_id and consegna.origine_tipo.model == "ordinevendita":
        return Fattura.objects.filter(ordine_id=consegna.origine_id, stato=Fattura.EMESSA).exclude(tipo=Fattura.NOTA_CREDITO).order_by("-data").first()
    return None


@transaction.atomic
def da_consegna(consegna, utente=None, motivo="difettoso"):
    """Un reso richiesto con tutte le righe del DDT (si riducono poi): rientro nello stesso magazzino."""
    if consegna.stato != consegna.FATTO:
        raise ValidationError("Il reso si fa da una consegna già spedita.")
    reso = Reso.objects.create(azienda=consegna.azienda, cliente=consegna.cliente, consegna=consegna, magazzino=consegna.magazzino,
                               motivo=motivo)
    fattura = fattura_della_consegna(consegna)
    if fattura is not None:
        reso.fattura_id = fattura.pk
        reso.save(update_fields=["fattura_id"])
    for r in consegna.righe.select_related("prodotto"):
        RigaReso.objects.create(reso=reso, prodotto=r.prodotto, quantita=r.quantita, lotti=r.lotti)
    numera(reso)
    return reso


def autorizza(reso, utente=None):
    if reso.stato != Reso.RICHIESTO:
        raise ValidationError("Si autorizza solo un reso richiesto.")
    if not reso.righe.exists():
        raise ValidationError("Il reso non ha righe.")
    numera(reso)
    reso.stato = Reso.AUTORIZZATO
    reso.save(update_fields=["stato"])


def rifiuta(reso, utente=None):
    if reso.stato not in (Reso.RICHIESTO, Reso.AUTORIZZATO):
        raise ValidationError("Il reso è già andato avanti.")
    reso.stato = Reso.RIFIUTATO
    reso.save(update_fields=["stato"])


class _Riga:
    def __init__(self, r):
        self.quantita, self.lotti = r.quantita, r.lotti


@transaction.atomic
def rientra(reso, utente=None):
    """La merce è arrivata: le righe «rimessa a magazzino» si caricano al costo di magazzino, quelle «scartata» no.
    Nessuna riga può restare da ispezionare."""
    if reso.stato != Reso.AUTORIZZATO:
        raise ValidationError("Prima autorizza il reso.")
    righe = list(reso.righe.select_related("prodotto"))
    da_vedere = [str(r.prodotto) for r in righe if r.esito == RigaReso.DA_VEDERE]
    if da_vedere:
        raise ValidationError("Decidi l'esito di ogni riga (a magazzino o scarto): " + ", ".join(da_vedere))
    ct = ContentType.objects.get_for_model(Reso)
    for r in righe:
        if r.esito != RigaReso.MAGAZZINO or not r.prodotto.a_magazzino:
            continue
        costo = costi.costo_corrente(r.prodotto)
        for lotto, q in lotti.per_entrata(_Riga(r), r.prodotto):
            Movimento.objects.create(azienda=reso.azienda, prodotto=r.prodotto, magazzino=reso.magazzino, lotto=lotto, quantita=q,
                                     tipo=Movimento.CARICO, causale=f"{reso}"[:200], utente=utente, content_type=ct, object_id=reso.pk,
                                     costo_unitario=costo)
    reso.stato, reso.rientrato_il = Reso.RIENTRATO, timezone.localdate()
    reso.save(update_fields=["stato", "rientrato_il"])


@transaction.atomic
def nota_di_credito(reso, utente=None):
    """La nota di credito in bozza sulla fattura del reso con le sole righe rese, al prezzo e IVA della fattura."""
    if not apps.is_installed("fatturazione"):
        raise ValidationError("Serve il modulo Fatturazione.")
    from fatturazione.models import Fattura, RigaFattura
    if reso.nota_credito is not None:
        raise ValidationError(f"C'è già la {reso.nota_credito}.")
    if reso.stato not in (Reso.AUTORIZZATO, Reso.RIENTRATO):
        raise ValidationError("La nota di credito si fa su un reso autorizzato.")
    fattura = reso.fattura or fattura_della_consegna(reso.consegna)
    if fattura is None:
        raise ValidationError("Non trovo la fattura del reso: la nota di credito va fatta a mano dalla fattura.")
    per_prodotto = {}
    for rf in fattura.righe.filter(prodotto__isnull=False, is_bollo=False):
        per_prodotto.setdefault(rf.prodotto_id, rf)
    mancanti = [str(r.prodotto) for r in reso.righe.select_related("prodotto") if r.prodotto_id not in per_prodotto]
    if mancanti:
        raise ValidationError(f"Nella {fattura} non ci sono: " + ", ".join(mancanti))
    nota = Fattura.objects.create(azienda=fattura.azienda, tipo=Fattura.NOTA_CREDITO, cliente=fattura.cliente, fattura_origine=fattura,
                                  causale=f"{reso} ({reso.get_motivo_display().lower()}) sulla fattura {fattura.numero}"[:200])
    for r in reso.righe.select_related("prodotto"):
        rf = per_prodotto[r.prodotto_id]
        RigaFattura.objects.create(fattura=nota, prodotto=r.prodotto, descrizione=rf.descrizione, quantita=r.quantita, prezzo=rf.prezzo,
                                   sconto=rf.sconto, aliquota=rf.aliquota)
    nota.ricalcola()
    reso.fattura_id, reso.nota_credito_id = fattura.pk, nota.pk
    if reso.stato == Reso.RIENTRATO:
        reso.stato = Reso.CHIUSO
    reso.save(update_fields=["fattura_id", "nota_credito_id", "stato"])
    return nota
