"""Ciclo di vita delle fatture: dall'ordine, emissione con numero e scadenze, incassi, note di credito."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import chatter, sequenze
from fiscale import calcoli
from fiscale.models import AliquotaIva

from .models import CassaPrevidenziale, DatiFiscali, Fattura, Incasso, RigaFattura, RiferimentoDDT, Ritenuta, Scadenza


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
        RigaFattura.objects.create(fattura=fattura, prodotto=r.prodotto, descrizione=r.descrizione, unita=r.unita,
                                   quantita=r.quantita, prezzo=r.prezzo, sconto=r.sconto, aliquota=r.aliquota)
    fattura.ricalcola()
    return fattura


def controlla(fattura):
    errori = []
    if not fattura.righe.exists():
        errori.append("La fattura non ha righe.")
    if (fattura.cliente.nazione or "IT") == "IT" and not (fattura.cliente.partita_iva or fattura.cliente.codice_fiscale):
        errori.append(f"Il cliente {fattura.cliente} non ha né partita IVA né codice fiscale.")
    if fattura.tipo in Fattura.CON_DDT and not fattura.ddt.exists():
        errori.append("Una fattura differita deve indicare almeno un DDT.")
    if fattura.tipo in Fattura.SCAMBIO_RUOLI and not (fattura.collegata_numero and fattura.collegata_data):
        errori.append("L'autofattura deve indicare numero e data della fattura del fornitore.")
    if (fattura.cig or fattura.cup or fattura.commessa or fattura.rif_data) and not fattura.rif_numero:
        errori.append("CIG, CUP e commessa vanno con il numero dell'ordine o del contratto a cui si riferiscono.")
    if fattura.cliente.pubblica_amministrazione and len(fattura.cliente.codice_sdi) != 6:
        errori.append(f"{fattura.cliente} è una Pubblica Amministrazione: serve il codice univoco ufficio di 6 caratteri.")
    if fattura.totale <= 0:
        errori.append("Il totale deve essere positivo (per stornare si emette una nota di credito).")
    stessa_serie = (Fattura.objects.filter(tipo__in=Fattura.AUTOFATTURE) if fattura.autofattura
                    else Fattura.objects.exclude(tipo__in=Fattura.AUTOFATTURE))
    successiva = (stessa_serie.filter(azienda=fattura.azienda, stato=Fattura.EMESSA, data__year=fattura.data.year,
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
    _addebita_bollo(fattura)
    numero = sequenze.prossimo("fatturazione.autofattura" if fattura.autofattura else "fatturazione.fattura", fattura.azienda)
    fattura.numero, fattura.stato, fattura.emessa_il = numero, Fattura.EMESSA, timezone.now()
    fattura.save(update_fields=["numero", "stato", "emessa_il"])
    if fattura.incassabile:
        modalita = fattura.termine_pagamento.modalita if fattura.termine_pagamento else "MP05"
        for data, importo in calcoli.scadenze(fattura.termine_pagamento, fattura.data, fattura.da_incassare):
            Scadenza.objects.create(fattura=fattura, data=data, importo=importo, modalita=modalita)
    else:
        fattura.pagata = True                         # note di credito e autofatture non si incassano
        fattura.save(update_fields=["pagata"])
        if fattura.tipo == Fattura.NOTA_CREDITO and fattura.fattura_origine_id:
            _compensa(fattura)
    return fattura


def _addebita_bollo(fattura):
    """Bollo a carico del cliente: una riga esclusa da IVA (art. 15), che non conta per la soglia."""
    dati = DatiFiscali.objects.filter(azienda=fattura.azienda).first()
    if not (fattura.bollo and dati and dati.bollo_al_cliente and fattura.incassabile) or fattura.righe.filter(is_bollo=True).exists():
        return
    esclusa = AliquotaIva.objects.filter(natura="N1", attiva=True).first()
    if esclusa is None:
        raise ValidationError("Per addebitare il bollo al cliente serve un'aliquota con natura N1.")
    RigaFattura.objects.create(fattura=fattura, descrizione="Imposta di bollo assolta in modo virtuale", quantita=1,
                               prezzo=fattura.bollo, aliquota=esclusa, soggetta_ritenuta=False, is_bollo=True)
    fattura.ricalcola()


def _aggiorna_scadenza(scadenza):
    """Da chiamare dopo ogni movimento: importo incassato, scadenza chiusa o riaperta, fattura incassata o no."""
    movimenti = scadenza.incassi.all()
    scadenza.incassato = sum((m.importo for m in movimenti), Decimal(0))
    scadenza.pagata = scadenza.incassato >= scadenza.importo
    ultimo = max((m.data for m in movimenti), default=None)
    scadenza.pagata_il = ultimo if scadenza.pagata else None
    scadenza.save(update_fields=["incassato", "pagata", "pagata_il"])
    fattura = scadenza.fattura
    fattura.pagata = not fattura.scadenze.filter(pagata=False).exists()
    fattura.save(update_fields=["pagata"])


@transaction.atomic
def registra_incasso(scadenza, importo=None, data=None, metodo="bonifico", tipo=Incasso.INCASSO, riferimento="", utente=None,
                     nota_credito=None):
    scadenza = Scadenza.objects.select_for_update().select_related("fattura").get(pk=scadenza.pk)
    importo = scadenza.residuo if importo is None else calcoli.arrotonda(importo)
    if importo <= 0:
        raise ValidationError("L'importo deve essere positivo.")
    if importo > scadenza.residuo:
        raise ValidationError(f"Restano da incassare {scadenza.residuo} €: non puoi registrarne {importo}.")
    incasso = Incasso.objects.create(scadenza=scadenza, importo=importo, data=data or timezone.localdate(), metodo=metodo,
                                     tipo=tipo, riferimento=riferimento, utente=utente, nota_credito=nota_credito)
    _aggiorna_scadenza(scadenza)
    return incasso


@transaction.atomic
def incassa_fattura(fattura, importo, data=None, metodo="bonifico", tipo=Incasso.INCASSO, riferimento="", utente=None):
    """Un importo sulla fattura: copre le scadenze dalla più vecchia. Restituisce gli incassi creati."""
    importo = calcoli.arrotonda(importo)
    aperte = list(fattura.scadenze.filter(pagata=False).order_by("data", "pk"))
    residuo = sum((s.residuo for s in aperte), Decimal(0))
    if importo <= 0:
        raise ValidationError("L'importo deve essere positivo.")
    if importo > residuo:
        raise ValidationError(f"Restano da incassare {residuo} €: non puoi registrarne {importo}.")
    creati = []
    for scadenza in aperte:
        if importo <= 0:
            break
        quota = min(importo, scadenza.residuo)
        creati.append(registra_incasso(scadenza, quota, data, metodo, tipo, riferimento, utente))
        importo -= quota
    return creati


@transaction.atomic
def annulla_incasso(incasso):
    scadenza = incasso.scadenza
    incasso.delete()
    _aggiorna_scadenza(scadenza)


def _compensa(nota):
    """Nota di credito emessa: scala il suo importo dalle scadenze aperte, a partire dall'ultima."""
    disponibile = nota.da_incassare
    for scadenza in nota.fattura_origine.scadenze.filter(pagata=False).order_by("-data", "-pk"):
        if disponibile <= 0:
            break
        quota = min(disponibile, scadenza.residuo)
        registra_incasso(scadenza, quota, nota.data, tipo=Incasso.COMPENSAZIONE, metodo="altro", nota_credito=nota,
                         riferimento=nota.numero)
        disponibile -= quota


def da_rimborsare(nota):
    """La parte della nota di credito già incassata dal cliente: non si compensa, va restituita."""
    compensato = sum((c.importo for c in nota.compensazioni.all()), Decimal(0))
    return max(nota.da_incassare - compensato, Decimal(0))


def incassa(scadenza, data=None):
    """Il residuo della scadenza, tutto insieme."""
    if scadenza.residuo > 0:
        registra_incasso(scadenza, None, data)


@transaction.atomic
def nota_di_credito(fattura):
    """Nota di credito in bozza che storna l'intera fattura emessa (le righe si possono poi ridurre)."""
    if fattura.stato != Fattura.EMESSA or fattura.tipo not in Fattura.STORNABILI:
        raise ValidationError("Si storna solo una fattura emessa.")
    nota = Fattura.objects.create(azienda=fattura.azienda, tipo=Fattura.NOTA_CREDITO, cliente=fattura.cliente,
                                  fattura_origine=fattura, causale=f"Storno della fattura {fattura.numero}")
    for r in fattura.righe.all():
        RigaFattura.objects.create(fattura=nota, prodotto=r.prodotto, descrizione=r.descrizione, quantita=r.quantita, unita=r.unita,
                                   prezzo=r.prezzo, sconto=r.sconto, aliquota=r.aliquota,
                                   soggetta_ritenuta=r.soggetta_ritenuta, is_bollo=r.is_bollo)
    for c in fattura.casse.all():
        CassaPrevidenziale.objects.create(fattura=nota, tipo=c.tipo, aliquota_cassa=c.aliquota_cassa, aliquota=c.aliquota,
                                          soggetta_ritenuta=c.soggetta_ritenuta)
    for r in fattura.righe_ritenuta.all():
        Ritenuta.objects.create(fattura=nota, tipo=r.tipo, aliquota_ritenuta=r.aliquota_ritenuta,
                                percentuale_base=r.percentuale_base, causale=r.causale)
    nota.ricalcola()
    return nota


@transaction.atomic
def da_consegne(consegne):
    """Fattura differita in bozza da più DDT dello stesso cliente: una riga per riga spedita, al prezzo dell'ordine
    se la consegna nasce da un ordine, altrimenti al prezzo del prodotto."""
    consegne = sorted(consegne, key=lambda c: (c.data, c.pk))
    if not consegne:
        raise ValidationError("Scegli almeno una consegna.")
    if len({c.cliente_id for c in consegne}) > 1:
        raise ValidationError("Una fattura differita è per un solo cliente: scegli consegne dello stesso destinatario.")
    spedite = [c for c in consegne if c.stato == "fatto"]
    if len(spedite) != len(consegne):
        raise ValidationError("Si fatturano solo le consegne già spedite, con il DDT.")
    prima = consegne[0]
    gia = RiferimentoDDT.objects.filter(fattura__azienda=prima.azienda, numero__in=[c.numero for c in consegne]).exclude(
        fattura__stato=Fattura.ANNULLATA).select_related("fattura")
    gia = [r for r in gia if not r.fattura.stornata]
    if gia:
        raise ValidationError(f"Il {gia[0]} è già in {gia[0].fattura}.")
    ordini = {c.origine_id: c.origine for c in consegne if c.origine_id and c.origine_tipo.model == "ordinevendita"}
    ordine = next(iter(ordini.values())) if len(ordini) == 1 else None
    fattura = Fattura.objects.create(azienda=prima.azienda, cliente=prima.cliente, tipo="TD24", ordine=ordine,
                                     termine_pagamento=ordine.termine_pagamento if ordine else None,
                                     causale="Fattura differita: " + ", ".join(c.numero for c in consegne))
    for c in consegne:
        RiferimentoDDT.objects.create(fattura=fattura, numero=c.numero[:20], data=c.data)
        ordine_c = ordini.get(c.origine_id)
        for r in c.righe.select_related("prodotto"):
            riga_ordine = ordine_c.righe.filter(prodotto=r.prodotto).first() if ordine_c else None
            RigaFattura.objects.create(fattura=fattura, prodotto=r.prodotto, descrizione=r.descrizione, quantita=r.quantita,
                                       unita=r.prodotto.unita,          # il DDT è nell'unità del prodotto: prezzo riportato a quella
                                       prezzo=(riga_ordine.prezzo / riga_ordine.per_unita).quantize(Decimal("0.0001")) if riga_ordine else None,
                                       sconto=riga_ordine.sconto if riga_ordine else 0,
                                       aliquota=riga_ordine.aliquota if riga_ordine else None)
    fattura.ricalcola()
    return fattura


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


__all__ = ["Decimal", "da_ordine", "fatture_attive", "annulla_da_ordine", "emetti", "incassa", "nota_di_credito", "controlla", "importo_con_segno", "registra_incasso",
           "incassa_fattura", "annulla_incasso", "da_consegne", "da_rimborsare"]


def link_pagamento(fattura):
    """Il link «Paga ora» della fattura se si paga online (modulo Pagamenti online con un fornitore attivo), altrimenti ""."""
    from django.apps import apps
    if not apps.is_installed("pagamenti"):
        return ""
    from pagamenti import servizi
    return servizi.link(fattura) if servizi.pagabile(fattura) else ""


def frase_pagamento(fattura):
    """Da mettere in coda a una frase delle email: «Può pagarla online…» con il link, oppure niente."""
    link = link_pagamento(fattura)
    return f"\nPuò pagarla online da questo link: {link}" if link else ""
