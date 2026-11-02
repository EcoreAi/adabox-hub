"""Ciclo di vita delle fatture: dall'ordine, emissione con numero e scadenze, incassi, note di credito."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import chatter, sequenze
from fiscale import calcoli

from .models import Fattura, RigaFattura, Scadenza


def fatture_attive(ordine):
    """Le fatture dell'ordine che lo coprono ancora: non annullate e non interamente stornate."""
    return [f for f in ordine.fatture.exclude(tipo=Fattura.NOTA_CREDITO).exclude(stato=Fattura.ANNULLATA) if not f.stornata]


@transaction.atomic
def da_ordine(ordine):
    """Fattura in bozza con le righe dell'ordine di vendita confermato; un ordine già fatturato non si rifattura."""
    ordine = type(ordine).objects.select_for_update().get(pk=ordine.pk)      # due clic insieme: passa uno solo
    if ordine.stato != "confermato":
        raise ValidationError("Si fattura solo un ordine confermato.")
    attive = fatture_attive(ordine)
    if attive:
        raise ValidationError(f"L'ordine {ordine.numero_ordine} è già fatturato con {attive[0]}: "
                              "per rifarla, storna prima la fattura con una nota di credito.")
    fattura = Fattura.objects.create(azienda=ordine.azienda, cliente=ordine.cliente, ordine=ordine,
                                     termine_pagamento=ordine.termine_pagamento,
                                     causale=f"Ordine {ordine.numero_ordine} del {ordine.data:%d/%m/%Y}")
    for r in ordine.righe.all():
        RigaFattura.objects.create(fattura=fattura, prodotto=r.prodotto, descrizione=r.descrizione,
                                   quantita=r.quantita, prezzo=r.prezzo, sconto=r.sconto, aliquota=r.aliquota)
    fattura.ricalcola()
    return fattura


def controlla(fattura):
    errori = []
    if not fattura.righe.exists():
        errori.append("La fattura non ha righe.")
    if not (fattura.cliente.partita_iva or fattura.cliente.codice_fiscale):
        errori.append(f"Il cliente {fattura.cliente} non ha né partita IVA né codice fiscale.")
    if fattura.totale <= 0:
        errori.append("Il totale deve essere positivo (per stornare si emette una nota di credito).")
    successiva = (Fattura.objects.filter(azienda=fattura.azienda, stato=Fattura.EMESSA, data__year=fattura.data.year,
                                         data__gt=fattura.data).order_by("-data").first())
    if successiva:
        errori.append(f"Nel {fattura.data.year} c'è già {successiva} del {successiva.data:%d/%m/%Y}: "
                      "la numerazione deve seguire l'ordine delle date.")
    return errori


@transaction.atomic
def emetti(fattura):
    """Numero progressivo dell'anno ({numero}/{anno}) e scadenze dal termine di pagamento."""
    if fattura.stato != Fattura.BOZZA:
        raise ValidationError("La fattura non è in bozza.")
    errori = controlla(fattura)
    if errori:
        raise ValidationError(errori)
    numero = sequenze.prossimo("fatturazione.fattura", fattura.azienda)
    fattura.numero, fattura.stato, fattura.emessa_il = numero, Fattura.EMESSA, timezone.now()
    fattura.save(update_fields=["numero", "stato", "emessa_il"])
    if fattura.tipo == Fattura.FATTURA:
        modalita = fattura.termine_pagamento.modalita if fattura.termine_pagamento else "MP05"
        for data, importo in calcoli.scadenze(fattura.termine_pagamento, fattura.data, fattura.totale):
            Scadenza.objects.create(fattura=fattura, data=data, importo=importo, modalita=modalita)
    else:
        fattura.pagata = True                         # la nota di credito non si incassa
        fattura.save(update_fields=["pagata"])
    return fattura


@transaction.atomic
def incassa(scadenza, data=None):
    scadenza.pagata, scadenza.pagata_il = True, data or timezone.localdate()
    scadenza.save(update_fields=["pagata", "pagata_il"])
    fattura = scadenza.fattura
    if not fattura.scadenze.filter(pagata=False).exists():
        fattura.pagata = True
        fattura.save(update_fields=["pagata"])


@transaction.atomic
def nota_di_credito(fattura):
    """Nota di credito in bozza che storna l'intera fattura emessa (le righe si possono poi ridurre)."""
    if fattura.stato != Fattura.EMESSA or fattura.tipo != Fattura.FATTURA:
        raise ValidationError("Si storna solo una fattura emessa.")
    nota = Fattura.objects.create(azienda=fattura.azienda, tipo=Fattura.NOTA_CREDITO, cliente=fattura.cliente,
                                  fattura_origine=fattura, causale=f"Storno della fattura {fattura.numero}")
    for r in fattura.righe.all():
        RigaFattura.objects.create(fattura=nota, prodotto=r.prodotto, descrizione=r.descrizione, quantita=r.quantita,
                                   prezzo=r.prezzo, sconto=r.sconto, aliquota=r.aliquota)
    nota.ricalcola()
    return nota


def annulla_da_ordine(sender, ordine, utente=None, **kwargs):
    """Ordine annullato: le bozze si annullano con lui; se c'è una fattura emessa va prima stornata."""
    emesse = [f for f in fatture_attive(ordine) if f.stato == Fattura.EMESSA]
    if emesse:
        raise ValidationError(f"{ordine} non si può annullare: è fatturato con {emesse[0]}. "
                              "Stornala prima con una nota di credito.")
    bozze = list(ordine.fatture.filter(stato=Fattura.BOZZA))
    for fattura in bozze:
        vecchi = chatter.valori(fattura, ["stato"])
        fattura.stato = Fattura.ANNULLATA
        fattura.save(update_fields=["stato"])
        chatter.traccia(fattura, vecchi, utente)
    return f"Fatture in bozza annullate: {len(bozze)}." if bozze else None


def importo_con_segno(fattura):
    return fattura.totale * fattura.segno


__all__ = ["Decimal", "da_ordine", "fatture_attive", "annulla_da_ordine", "emetti", "incassa", "nota_di_credito", "controlla", "importo_con_segno"]
