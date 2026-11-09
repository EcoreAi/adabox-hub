"""La vita di un contratto ricorrente: attivazione, fatture dei periodi, rinnovi, disdette, ISTAT e previsione dei ricavi."""
import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core import chatter, lavori, modelli_email, parametri
from core.models import Messaggio
from fatturazione import operazioni as fatture
from fatturazione.models import Fattura, RigaFattura
from fiscale import calcoli

from .models import Adeguamento, Canone, FatturaCanone, piu_mesi

logger = logging.getLogger(__name__)
MAX_PER_GIRO = 100


def _nota(canone, testo, utente=None):
    chatter.scrivi(canone, utente, testo, tipo=Messaggio.NOTA)


def _allinea_scadenza(canone, oggi):
    """Porta la scadenza oltre oggi per i rinnovi taciti già maturati."""
    if not canone.durata_mesi:
        canone.scadenza = None
        return
    canone.scadenza = canone.scadenza or canone.fine_termine()
    if canone.rinnovo_tacito:
        while canone.scadenza < oggi:
            canone.scadenza = _rinnovata(canone)


def _rinnovata(canone):
    return piu_mesi(canone.scadenza + datetime.timedelta(days=1), canone.durata_mesi) - datetime.timedelta(days=1)


@transaction.atomic
def attiva(canone, utente=None):
    """Da qui si fattura, ma dal periodo in corso: i periodi passati non partono mai da soli."""
    if canone.stato != Canone.BOZZA:
        raise ValidationError("Il contratto è già stato attivato.")
    if not canone.righe.exists() or canone.imponibile <= 0:
        raise ValidationError("Aggiungi almeno una riga con un importo.")
    oggi = timezone.localdate()
    canone.scadenza = None
    _allinea_scadenza(canone, oggi)
    if canone.scadenza and canone.scadenza < oggi:
        raise ValidationError(f"Il contratto è scaduto il {canone.scadenza:%d/%m/%Y} e non si rinnova: controlla le date.")
    canone.prossimo_periodo = canone.periodo_che_contiene(oggi)
    canone.stato = Canone.ATTIVO
    canone.save(update_fields=["stato", "scadenza", "prossimo_periodo"])
    saltati = canone.prossimo_periodo > canone.inizio
    _nota(canone, f"Contratto attivato: si fattura dal periodo del {canone.prossimo_periodo:%d/%m/%Y}.", utente)
    return saltati


@transaction.atomic
def sospendi(canone, utente=None):
    if canone.stato != Canone.ATTIVO:
        raise ValidationError("Si sospende solo un contratto attivo.")
    canone.stato = Canone.SOSPESO
    canone.save(update_fields=["stato"])
    _nota(canone, "Contratto sospeso: nessuna fattura finché non riprende.", utente)


@transaction.atomic
def riprendi(canone, utente=None):
    """Si riparte dal periodo in corso: quelli della sospensione non si fatturano."""
    if canone.stato != Canone.SOSPESO:
        raise ValidationError("Il contratto non è sospeso.")
    oggi = timezone.localdate()
    _allinea_scadenza(canone, oggi)
    canone.prossimo_periodo = max(canone.prossimo_periodo, canone.periodo_che_contiene(oggi))
    canone.stato = Canone.ATTIVO
    canone.save(update_fields=["stato", "scadenza", "prossimo_periodo"])
    _nota(canone, f"Contratto ripreso: si fattura dal periodo del {canone.prossimo_periodo:%d/%m/%Y}.", utente)


def termine_disdetta(canone, giorno):
    """Fino a quando dura il contratto se lo si disdice in `giorno`."""
    if canone.scadenza:
        if giorno <= canone.limite_disdetta() or not canone.rinnovo_tacito:
            return canone.scadenza
        return _rinnovata(canone)                    # preavviso passato: vale il termine successivo
    dal = canone.periodo_che_contiene(giorno + datetime.timedelta(days=canone.preavviso_giorni))
    return canone.fine_periodo(dal)


@transaction.atomic
def disdici(canone, utente=None, giorno=None):
    if canone.stato != Canone.ATTIVO:
        raise ValidationError("Si disdice solo un contratto attivo.")
    giorno = giorno or timezone.localdate()
    canone.disdetto_il, canone.cessa_il, canone.stato = giorno, termine_disdetta(canone, giorno), Canone.DISDETTO
    canone.save(update_fields=["disdetto_il", "cessa_il", "stato"])
    _nota(canone, f"Disdetta registrata il {giorno:%d/%m/%Y}: il contratto si fattura fino al {canone.cessa_il:%d/%m/%Y}.", utente)
    return canone.cessa_il


@transaction.atomic
def revoca_disdetta(canone, utente=None):
    if canone.stato != Canone.DISDETTO:
        raise ValidationError("Il contratto non è disdetto.")
    canone.disdetto_il, canone.cessa_il, canone.stato = None, None, Canone.ATTIVO
    canone.save(update_fields=["disdetto_il", "cessa_il", "stato"])
    _nota(canone, "Disdetta revocata: il contratto prosegue.", utente)


def _chiudi_o_rinnova(canone, oggi):
    """A periodo nuovo iniziato: finisce, o riparte per un altro termine. Vero se il contratto è finito."""
    dal = canone.prossimo_periodo
    if oggi < dal:
        return False
    if canone.cessa_il and dal > canone.cessa_il:
        return _concludi(canone)
    if canone.scadenza and not canone.durata_mesi:         # è diventato senza scadenza
        canone.scadenza = None
        canone.save(update_fields=["scadenza"])
    if canone.scadenza and dal > canone.scadenza:
        if not (canone.rinnovo_tacito or canone.cessa_il):
            return _concludi(canone)
        while canone.scadenza < dal:
            canone.scadenza = _rinnovata(canone)
        canone.save(update_fields=["scadenza"])
        _nota(canone, f"Contratto rinnovato fino al {canone.scadenza:%d/%m/%Y}.")
    return False


def _concludi(canone):
    canone.stato = Canone.CONCLUSO
    canone.save(update_fields=["stato"])
    _nota(canone, "Contratto concluso.")
    return True


def _viva(fattura):
    return not (fattura.stato == Fattura.ANNULLATA or fattura.stornata)


def _salta_fatturati(canone):
    """Dopo aver riportato indietro il prossimo periodo si rifà solo ciò che manca, mai un periodo con una fattura valida."""
    while True:
        voce = FatturaCanone.objects.select_related("fattura").filter(canone=canone, dal=canone.prossimo_periodo).first()
        if voce is None or not _viva(voce.fattura):
            return
        canone.prossimo_periodo = canone.dopo(canone.prossimo_periodo)
        canone.save(update_fields=["prossimo_periodo"])


def _crea_fattura(canone, dal):
    al = canone.fine_periodo(dal)
    esistente = FatturaCanone.objects.select_related("fattura").filter(canone=canone, dal=dal).first()
    if esistente:
        esistente.delete()          # _salta_fatturati lascia passare solo una fattura annullata o stornata
    periodo = f"dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}"
    fattura = Fattura.objects.create(azienda=canone.azienda, cliente=canone.cliente, termine_pagamento=canone.termine_pagamento,
                                     causale=f"{canone.nome} {periodo}"[:200], rif_tipo="contratto", rif_numero=canone.numero[:20])
    for r in canone.righe.select_related("prodotto", "aliquota"):
        RigaFattura.objects.create(fattura=fattura, prodotto=r.prodotto, descrizione=f"{r.descrizione} · {periodo}"[:250],
                                   unita=r.prodotto.unita if r.prodotto_id else None,
                                   quantita=r.quantita, prezzo=r.prezzo, sconto=r.sconto, aliquota=r.aliquota)
    fattura.ricalcola()
    FatturaCanone.objects.create(canone=canone, fattura=fattura, dal=dal, al=al)
    canone.prossimo_periodo = canone.dopo(dal)
    canone.save(update_fields=["prossimo_periodo"])
    return fattura


@transaction.atomic
def fattura_prossimo(canone, utente=None):
    """Il prossimo periodo, subito e anche in anticipo sulla data: da «Fattura ora». Resta in bozza."""
    canone = Canone.objects.select_for_update().get(pk=canone.pk)    # due clic insieme: passa uno solo
    if not canone.fatturabile:
        raise ValidationError("Si fattura solo un contratto attivo.")
    _salta_fatturati(canone)
    if canone.cessa_il and canone.prossimo_periodo > canone.cessa_il:
        raise ValidationError(f"Il contratto finisce il {canone.cessa_il:%d/%m/%Y}: non ci sono altri periodi.")
    if canone.scadenza and canone.prossimo_periodo > canone.scadenza and not canone.rinnovo_tacito and not canone.cessa_il:
        raise ValidationError(f"Il contratto scade il {canone.scadenza:%d/%m/%Y}: non ci sono altri periodi.")
    fattura = _crea_fattura(canone, canone.prossimo_periodo)
    _nota(canone, f"{fattura} creata a mano per il periodo {fattura.da_canone.dal:%d/%m/%Y} – {fattura.da_canone.al:%d/%m/%Y}.", utente)
    return fattura


def _emetti_e_invia(canone, fattura):
    """Se la fattura non si può emettere resta in bozza, con il motivo nelle note: non ferma gli altri contratti."""
    try:
        with transaction.atomic():
            fatture.emetti(fattura)
    except ValidationError as e:
        _nota(canone, f"{fattura} resta in bozza: {' '.join(e.messages)}")
        return
    if canone.invio_automatico:
        if canone.cliente.email:
            lavori.accoda("fatturazione.lavori.invia", fattura_id=fattura.pk)
        else:
            _nota(canone, f"{fattura} non inviata: il cliente non ha un indirizzo email.")


def _giro_contratto(canone, oggi, rimaste):
    """Fatture dovute di un contratto. Quelle create; si ferma a `rimaste`."""
    fatte = 0
    with transaction.atomic():
        canone = Canone.objects.select_for_update().get(pk=canone.pk)
        while fatte < rimaste and canone.fatturabile:
            _salta_fatturati(canone)
            if _chiudi_o_rinnova(canone, oggi) or canone.data_fattura(canone.prossimo_periodo) > oggi:
                break
            fattura = _crea_fattura(canone, canone.prossimo_periodo)
            fatte += 1
            if canone.emissione_automatica:
                _emetti_e_invia(canone, fattura)
    return fatte


def _in_avviso(canone, oggi):
    if not canone.scadenza or canone.stato != Canone.ATTIVO or canone.avviso_per == canone.scadenza:
        return False
    giorni = parametri.leggi("ricorrenti.giorni_avviso", canone.azienda)
    return oggi >= canone.limite_disdetta() - datetime.timedelta(days=giorni)


def _avvisa_scadenza(canone):
    """Una volta per ogni scadenza, in tempo per decidere se disdire."""
    canone.avviso_per = canone.scadenza
    canone.save(update_fields=["avviso_per"])
    if not (canone.responsabile_id and canone.responsabile.email):
        return
    if canone.rinnovo_tacito:
        cosa = f"Si rinnova da solo: per disdirlo c'è tempo fino al {canone.limite_disdetta():%d/%m/%Y}."
    else:
        cosa = "Non si rinnova da solo: se il cliente prosegue, va rifatto."
    modelli_email.messaggio("ricorrenti.in_scadenza", canone.azienda, {
        "contratto": str(canone), "cliente": canone.cliente.nome, "scadenza": f"{canone.scadenza:%d/%m/%Y}", "cosa_succede": cosa,
        "link": f"{settings.SITO_URL}{reverse('ricorrenti:canoni_dettaglio', args=[canone.pk])}"},
        [canone.responsabile.email]).send(fail_silently=True)


def giro():
    """Ogni ora: rinnovi, conclusioni, fatture dovute e avvisi. Ripeterlo non cambia nulla, e al massimo MAX_PER_GIRO fatture."""
    oggi = timezone.localdate()
    fatte = 0
    for canone in Canone.objects.filter(stato__in=(Canone.ATTIVO, Canone.DISDETTO)).select_related("azienda", "cliente", "responsabile"):
        if fatte < MAX_PER_GIRO:
            try:
                fatte += _giro_contratto(canone, oggi, MAX_PER_GIRO - fatte)
            except Exception:                    # un contratto con dati impossibili non ferma gli altri
                logger.exception("Contratto ricorrente %s: giro non riuscito", canone.pk)
            canone.refresh_from_db()
        if _in_avviso(canone, oggi):
            _avvisa_scadenza(canone)
    return fatte


def fattura_eliminata(sender, instance, **kwargs):
    """Una bozza eliminata lascia un periodo senza fattura: va detto, ma non si ricrea da sola."""
    voce = FatturaCanone.objects.filter(fattura=instance).select_related("canone").first()
    if voce:
        _nota(voce.canone, f"La fattura del periodo {voce.dal:%d/%m/%Y} – {voce.al:%d/%m/%Y} è stata eliminata. Per rifarla "
                           f"riporta «prossimo periodo» al {voce.dal:%d/%m/%Y}.")


# ---------- ISTAT

@transaction.atomic
def adegua(canone, percentuale, giorno=None, utente=None):
    """Applica la percentuale ai prezzi. Il dato lo indica chi adegua: una volta al giorno, così un doppio clic non conta due volte."""
    giorno = giorno or timezone.localdate()
    if not Decimal(0) < percentuale <= Decimal(100):
        raise ValidationError("La percentuale va da 0 a 100.")
    if Adeguamento.objects.filter(canone=canone, data=giorno).exists():
        raise ValidationError(f"{canone} è già stato adeguato oggi.")
    prima = canone.imponibile
    for r in canone.righe.all():
        r.prezzo = calcoli.arrotonda(r.prezzo * (100 + percentuale) / 100)
        r.save()
    canone.ricalcola()
    voce = Adeguamento.objects.create(canone=canone, data=giorno, percentuale=percentuale, prima=prima, dopo=canone.imponibile)
    _nota(canone, f"Adeguamento del {percentuale}%: da {prima} € a {canone.imponibile} € a periodo.", utente)
    return voce


def ultimo_adeguamento(canone):
    return canone.adeguamenti.first()


# ---------- ricavi

def _inizi_mese(primo, mesi):
    return [piu_mesi(primo, i) for i in range(mesi)]


def previsione(canoni, mesi=12, oggi=None):
    """[(mese, importo)] di quanto si fatturerà, senza contare i contratti oltre la loro fine nota."""
    oggi = oggi or timezone.localdate()
    primo = oggi.replace(day=1)
    colonne = _inizi_mese(primo, mesi)
    somme = {m: Decimal(0) for m in colonne}
    limite = piu_mesi(primo, mesi)
    for c in canoni:
        dal = c.prossimo_periodo
        scadenza = c.scadenza
        while dal and dal < piu_mesi(limite, c.periodicita):
            if c.cessa_il and dal > c.cessa_il:
                break
            if scadenza and c.durata_mesi and dal > scadenza:
                if not c.rinnovo_tacito:
                    break
                scadenza = piu_mesi(scadenza + datetime.timedelta(days=1), c.durata_mesi) - datetime.timedelta(days=1)
            quando = max(c.data_fattura(dal), oggi)
            if quando >= limite:
                break
            somme[quando.replace(day=1)] += c.imponibile
            dal = c.dopo(dal)
    return [(m, somme[m]) for m in colonne]


def attivi(qs):
    return qs.filter(stato__in=(Canone.ATTIVO, Canone.DISDETTO))


def ricavi_mensili(qs):
    return sum((c.mensile for c in attivi(qs)), Decimal(0))
