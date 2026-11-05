"""Il ciclo di vita dell'ordine: conferma (con approvazioni e contratto), approvazione, annullamento, gare, contratti.
Bottoni, pagine e lavori passano tutti da qui, così le regole valgono da qualunque parte arrivi la richiesta."""
import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core import attivita, chatter, lavori, sequenze
from core.models import TipoAttivita

from . import listini
from .models import (Approvazione, ContrattoQuadro, Gara, OrdineAcquisto, RegolaApprovazione, RigaAcquisto,
                     RigaContratto)
from .segnali import ordine_acquisto_annullato, ordine_acquisto_confermato

CAMPI_TRACCIATI = ["stato", "fornitore", "totale", "consegna_prevista"]


def _cambia_stato(ordine, stato, utente, **altri):
    vecchi = chatter.valori(ordine, CAMPI_TRACCIATI)
    ordine.stato = stato
    for campo, valore in altri.items():
        setattr(ordine, campo, valore)
    ordine.save(update_fields=["stato", *altri])
    chatter.traccia(ordine, vecchi, utente)


def applica_condizioni(ordine):
    """Pagamento e consegna prevista dalle condizioni del fornitore, solo se non sono già indicati."""
    condizioni = listini.condizioni(ordine.fornitore)
    if condizioni is None:
        return
    if ordine.termine_pagamento_id is None:
        ordine.termine_pagamento = condizioni.termine_pagamento
    if ordine.consegna_prevista is None and condizioni.giorni_consegna is not None:
        ordine.consegna_prevista = ordine.data + datetime.timedelta(days=condizioni.giorni_consegna)


# --- Contratti quadro

def consumato(riga_contratto):
    """Quantità già richiamata: conta solo gli ordini confermati, così annullarne uno libera il residuo."""
    return (RigaAcquisto.objects.filter(ordine__contratto_id=riga_contratto.contratto_id,
                                        ordine__stato=OrdineAcquisto.CONFERMATO, prodotto=riga_contratto.prodotto)
            .aggregate(t=Sum("quantita"))["t"] or Decimal(0))


def residui_contratto(contratto):
    righe = []
    for r in contratto.righe.select_related("prodotto", "prodotto__unita"):
        preso = consumato(r)
        righe.append({"riga": r, "consumato": preso, "residuo": None if r.quantita is None else r.quantita - preso})
    return righe


def _controlla_contratto(ordine):
    if not ordine.contratto_id:
        return
    contratto = ContrattoQuadro.objects.select_for_update().get(pk=ordine.contratto_id)   # due conferme non scavalcano il residuo
    oggi = timezone.localdate()
    if contratto.stato != ContrattoQuadro.ATTIVO:
        raise ValidationError(f"Il contratto {contratto} non è attivo.")
    if contratto.dal > oggi or (contratto.al and contratto.al < oggi):
        raise ValidationError(f"Il contratto {contratto} non è in vigore oggi.")
    if contratto.fornitore_id != ordine.fornitore_id:
        raise ValidationError(f"Il contratto {contratto} è con un altro fornitore.")
    limiti = {r.prodotto_id: r for r in contratto.righe.select_related("prodotto")}
    richiesto = {}
    for r in ordine.righe.exclude(prodotto=None):
        richiesto[r.prodotto_id] = richiesto.get(r.prodotto_id, Decimal(0)) + r.quantita
    oltre = []
    for prodotto_id, quantita in richiesto.items():
        limite = limiti.get(prodotto_id)
        if limite is not None and limite.quantita is not None:
            residuo = limite.quantita - consumato(limite)
            if quantita > residuo:
                oltre.append(f"{limite.prodotto} (residuo {residuo:g}, richiesti {quantita:g})")
    if oltre:
        raise ValidationError("Oltre il contratto: " + ", ".join(oltre))


def attiva_contratto(contratto, utente=None):
    if contratto.stato != ContrattoQuadro.BOZZA:
        raise ValidationError("Il contratto non è in bozza.")
    if not contratto.righe.exists():
        raise ValidationError("Il contratto non ha righe.")
    contratto.numero = contratto.numero or sequenze.prossimo("acquisti.contratto", contratto.azienda)
    contratto.stato = ContrattoQuadro.ATTIVO
    contratto.save(update_fields=["numero", "stato"])
    chatter.scrivi(contratto, utente, "Contratto attivato.", tipo="nota")


def chiudi_contratto(contratto, utente=None):
    if contratto.stato != ContrattoQuadro.ATTIVO:
        raise ValidationError("Il contratto non è attivo.")
    contratto.stato = ContrattoQuadro.CHIUSO
    contratto.save(update_fields=["stato"])
    chatter.scrivi(contratto, utente, "Contratto chiuso.", tipo="nota")


@transaction.atomic
def richiamo(contratto, utente=None):
    """Un ordine in bozza con il residuo del contratto ai suoi prezzi; il buyer corregge le quantità."""
    if contratto.stato != ContrattoQuadro.ATTIVO:
        raise ValidationError("Il contratto non è attivo.")
    residui = residui_contratto(contratto)
    aperte = [x for x in residui if x["residuo"] is None or x["residuo"] > 0]
    if not aperte:
        raise ValidationError("Il contratto è già stato richiamato per intero.")
    ordine = _nuovo_ordine(contratto.azienda, contratto.fornitore, utente, contratto=contratto,
                           riferimento_fornitore=contratto.riferimento_fornitore)
    for x in aperte:
        r = x["riga"]
        RigaAcquisto.objects.create(ordine=ordine, prodotto=r.prodotto, prezzo=r.prezzo,
                                    quantita=x["residuo"] if x["residuo"] is not None else Decimal(1))
    ordine.ricalcola()
    return ordine


def _nuovo_ordine(azienda, fornitore, utente=None, **campi):
    ordine = OrdineAcquisto(azienda=azienda, fornitore=fornitore, buyer=utente,
                            numero=sequenze.prossimo("acquisti.ordine", azienda), **campi)
    applica_condizioni(ordine)
    ordine.save()
    return ordine


# --- Approvazioni

def regole_per(ordine):
    """Le regole attive che valgono per l'ordine, in ordine di livello."""
    categorie = set(ordine.righe.exclude(prodotto__categoria=None).values_list("prodotto__categoria_id", flat=True))
    return [r for r in RegolaApprovazione.objects.filter(azienda=ordine.azienda, attiva=True)
            if ordine.imponibile >= r.soglia and (r.categoria_id is None or r.categoria_id in categorie)]


def in_attesa(ordine):
    return ordine.approvazioni.filter(esito=Approvazione.ATTESA).select_related("regola")


def passaggio_corrente(ordine):
    """Il primo passaggio ancora da decidere: i livelli si approvano in ordine."""
    return in_attesa(ordine).order_by("livello", "pk").first()


def puo_decidere(utente, ordine, approvazione=None):
    """Chi compra non approva se stesso; il superuser può, per chi lavora da solo, e resta scritto nel chatter."""
    approvazione = approvazione or passaggio_corrente(ordine)
    if approvazione is None:
        return False
    if utente.is_superuser:
        return True
    if utente.pk in (ordine.buyer_id, approvazione.richiesta_da_id):
        return False
    if utente.has_perm("acquisti.approva_ordini"):
        return True
    return bool(approvazione.regola_id and approvazione.regola.approvatori.filter(pk=utente.pk).exists())


def _approvatori(approvazione):
    from django.contrib.auth import get_user_model
    if not approvazione.regola_id:
        return []
    return list(get_user_model().objects.filter(pk__in=approvazione.regola.approvatori.values("pk"), is_active=True))


def _avvisa_passaggio(ordine, utente):
    """Il passaggio corrente finisce tra le attività di chi deve decidere, che segue anche l'ordine."""
    corrente = passaggio_corrente(ordine)
    if corrente is None:
        return
    persone = [u for u in _approvatori(corrente) if u.pk not in (ordine.buyer_id, corrente.richiesta_da_id)]
    tipo = TipoAttivita.objects.filter(nome="Da fare").first() or TipoAttivita.objects.first()
    for persona in persone:
        chatter.segui(ordine, persona)
        if tipo is not None:
            attivita.pianifica(ordine, tipo, persona, riepilogo=f"Approva l'ordine {ordine} ({corrente.nome_regola})",
                               creato_da=utente)
    chatter.scrivi(ordine, utente, f"Da approvare: {corrente.nome_regola}, imponibile {ordine.imponibile} €.",
                   tipo="messaggio")


def _chiudi_attivita(ordine):
    testo = f"Approva l'ordine {ordine}"
    attivita.di(ordine).filter(riepilogo__startswith=testo).delete()


@transaction.atomic
def conferma(ordine, utente=None):
    """True se l'ordine è confermato, False se è passato in approvazione. ValidationError se non si può."""
    ordine = OrdineAcquisto.objects.select_for_update().get(pk=ordine.pk)      # il doppio clic non crea due ricevimenti
    if not ordine.modificabile:
        raise ValidationError(f"{ordine} non è da confermare.")
    if not ordine.righe.exists():
        raise ValidationError("L'ordine non ha righe.")
    _controlla_contratto(ordine)
    ordine.approvazioni.filter(esito__in=[Approvazione.ATTESA, Approvazione.RIFIUTATA]).update(esito=Approvazione.SUPERATA)
    regole = regole_per(ordine)
    if regole:
        Approvazione.objects.bulk_create(
            Approvazione(ordine=ordine, regola=r, nome_regola=r.nome, livello=r.livello, imponibile=ordine.imponibile,
                         richiesta_da=utente) for r in regole)
        _cambia_stato(ordine, OrdineAcquisto.DA_APPROVARE, utente)
        _avvisa_passaggio(ordine, utente)
        return False
    _conferma_definitiva(ordine, utente)
    return True


def _conferma_definitiva(ordine, utente):
    _cambia_stato(ordine, OrdineAcquisto.CONFERMATO, utente, confermato_il=timezone.localdate())
    ordine_acquisto_confermato.send(sender=OrdineAcquisto, ordine=ordine, utente=utente)
    if ordine.gara_id:
        _chiudi_gara(ordine, utente)


@transaction.atomic
def approva(ordine, utente):
    """True se con questa approvazione l'ordine è confermato; False se manca ancora un livello."""
    ordine = OrdineAcquisto.objects.select_for_update().get(pk=ordine.pk)
    if ordine.stato != OrdineAcquisto.DA_APPROVARE:
        raise ValidationError(f"{ordine} non è da approvare.")
    corrente = passaggio_corrente(ordine)
    if corrente is None or not puo_decidere(utente, ordine, corrente):
        raise PermissionDenied
    _controlla_contratto(ordine)                                     # il residuo può essere cambiato nel frattempo
    corrente.esito, corrente.decisa_da, corrente.decisa_il = Approvazione.APPROVATA, utente, timezone.now()
    corrente.save(update_fields=["esito", "decisa_da", "decisa_il"])
    _chiudi_attivita(ordine)
    chatter.scrivi(ordine, utente, f"Approvato: {corrente.nome_regola}.", tipo="nota")
    if in_attesa(ordine).exists():
        _avvisa_passaggio(ordine, utente)
        return False
    _conferma_definitiva(ordine, utente)
    return True


@transaction.atomic
def rifiuta(ordine, utente):
    """L'ordine torna richiesta: il buyer lo corregge e lo ripresenta, con tutte le approvazioni da rifare."""
    ordine = OrdineAcquisto.objects.select_for_update().get(pk=ordine.pk)
    if ordine.stato != OrdineAcquisto.DA_APPROVARE:
        raise ValidationError(f"{ordine} non è da approvare.")
    corrente = passaggio_corrente(ordine)
    if corrente is None or not puo_decidere(utente, ordine, corrente):
        raise PermissionDenied
    corrente.esito, corrente.decisa_da, corrente.decisa_il = Approvazione.RIFIUTATA, utente, timezone.now()
    corrente.save(update_fields=["esito", "decisa_da", "decisa_il"])
    ordine.approvazioni.filter(esito=Approvazione.ATTESA).update(esito=Approvazione.SUPERATA)
    _chiudi_attivita(ordine)
    _cambia_stato(ordine, OrdineAcquisto.BOZZA, utente)
    if ordine.gara_id:
        Gara.objects.filter(pk=ordine.gara_id, vincitore=ordine).update(vincitore=None)
    chatter.scrivi(ordine, utente, f"Approvazione rifiutata: {corrente.nome_regola}. L'ordine torna da correggere.",
                   tipo="messaggio")


@transaction.atomic
def annulla(ordine, utente=None):
    """Testo dell'esito. ValidationError (dal magazzino) se la merce si è già mossa: resta tutto com'era."""
    ordine = OrdineAcquisto.objects.select_for_update().get(pk=ordine.pk)
    if ordine.stato == OrdineAcquisto.ANNULLATO:
        raise ValidationError(f"{ordine} è già annullato.")
    _cambia_stato(ordine, OrdineAcquisto.ANNULLATO, utente)
    ordine.approvazioni.filter(esito=Approvazione.ATTESA).update(esito=Approvazione.SUPERATA)
    _chiudi_attivita(ordine)
    risposte = ordine_acquisto_annullato.send(sender=OrdineAcquisto, ordine=ordine, utente=utente)
    if ordine.gara_id:
        Gara.objects.filter(pk=ordine.gara_id, vincitore=ordine).update(vincitore=None)
    return " ".join([f"{ordine} annullato.", *(testo for _, testo in risposte if testo)])


def invia(ordine, utente=None):
    """Accoda l'invio al fornitore; la richiesta in bozza diventa «inviata». ValidationError se non si può."""
    if not ordine.modificabile:
        raise ValidationError("Solo una richiesta si invia.")
    if not ordine.fornitore.email:
        raise ValidationError(f"Il fornitore {ordine.fornitore} non ha un indirizzo email.")
    lavori.accoda("acquisti.lavori.invia", ordine_id=ordine.pk, utente_id=getattr(utente, "pk", None))
    if ordine.stato == OrdineAcquisto.BOZZA:
        _cambia_stato(ordine, OrdineAcquisto.INVIATO, utente)


# --- Gare

@transaction.atomic
def crea_offerte(gara, utente=None):
    """Un ordine in bozza per ogni fornitore invitato che non ne ha ancora uno. Quanti ne ha creati."""
    if gara.stato != Gara.APERTA:
        raise ValidationError("La gara non è aperta.")
    righe = list(gara.righe.select_related("prodotto"))
    if not righe:
        raise ValidationError("La gara non ha righe.")
    if not gara.numero:
        gara.numero = sequenze.prossimo("acquisti.gara", gara.azienda)
        gara.save(update_fields=["numero"])
    presenti = set(gara.offerte.exclude(stato=OrdineAcquisto.ANNULLATO).values_list("fornitore_id", flat=True))
    creati = 0
    for fornitore in gara.fornitori.exclude(pk__in=presenti):
        ordine = _nuovo_ordine(gara.azienda, fornitore, utente, gara=gara)
        for r in righe:
            RigaAcquisto.objects.create(ordine=ordine, prodotto=r.prodotto, descrizione=r.descrizione, quantita=r.quantita)
        ordine.ricalcola()
        creati += 1
    return creati


def invia_offerte(gara, utente=None):
    """(inviate, nomi dei fornitori senza email). Riguarda solo le richieste non ancora inviate."""
    inviate, senza = 0, []
    for ordine in gara.offerte.filter(stato=OrdineAcquisto.BOZZA).select_related("fornitore"):
        if not ordine.fornitore.email:
            senza.append(ordine.fornitore.nome)
            continue
        invia(ordine, utente)
        inviate += 1
    return inviate, senza


@transaction.atomic
def aggiudica(gara, ordine, utente=None):
    """Conferma l'offerta scelta (passando dalle approvazioni, se servono). True se è già confermata."""
    gara = Gara.objects.select_for_update().get(pk=gara.pk)
    if gara.stato != Gara.APERTA:
        raise ValidationError("La gara non è aperta.")
    if ordine.gara_id != gara.pk or not ordine.modificabile:
        raise ValidationError("Questa offerta non si può aggiudicare.")
    gara.vincitore = ordine
    gara.save(update_fields=["vincitore"])
    return conferma(ordine, utente)


def _chiudi_gara(vincitore, utente):
    """Un'offerta confermata chiude la gara: le altre si annullano. Vale anche se la conferma è partita dall'ordine."""
    gara = Gara.objects.select_for_update().get(pk=vincitore.gara_id)
    if gara.stato != Gara.APERTA:
        return
    gara.stato, gara.vincitore = Gara.AGGIUDICATA, vincitore
    gara.save(update_fields=["stato", "vincitore"])
    aperte = gara.offerte.exclude(pk=vincitore.pk).filter(
        stato__in=[OrdineAcquisto.BOZZA, OrdineAcquisto.INVIATO, OrdineAcquisto.DA_APPROVARE])
    for altra in aperte:
        annulla(altra, utente)
    chatter.scrivi(gara, utente, f"Aggiudicata a {vincitore.fornitore} con l'ordine {vincitore}.", tipo="nota")


@transaction.atomic
def annulla_gara(gara, utente=None):
    gara = Gara.objects.select_for_update().get(pk=gara.pk)
    if gara.stato != Gara.APERTA:
        raise ValidationError("La gara non è aperta.")
    for offerta in gara.offerte.filter(stato__in=[OrdineAcquisto.BOZZA, OrdineAcquisto.INVIATO, OrdineAcquisto.DA_APPROVARE]):
        annulla(offerta, utente)
    gara.stato = Gara.ANNULLATA
    gara.save(update_fields=["stato"])
