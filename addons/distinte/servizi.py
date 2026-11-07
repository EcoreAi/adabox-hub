"""Distinte dalle scadenze aperte: quali si possono mettere, creazione, file per la banca, esiti."""
import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from banca.models import iban_valido
from fatturazione import operazioni
from fatturazione.models import Fattura, Scadenza
from sdi import passive
from sdi.models import FatturaPassiva, ScadenzaPassiva

from . import riba, sepa
from .models import ConfigConto, CoordinateBancarie, Distinta, Mandato, VoceDistinta

MODALITA = {Distinta.SDD: {"MP19", "MP20", "MP21", "MP09", "MP10", "MP11", "MP16"}, Distinta.RIBA: {"MP12"}}
METODO = {Distinta.SDD: "sdd", Distinta.RIBA: "riba"}


@dataclass
class Candidato:
    chiave: str                  # "a<pk>" scadenza attiva, "p<pk>" scadenza passiva
    scadenza: object
    fattura: object
    nome: str
    importo: Decimal
    data: object
    iban: str = ""
    mandato: Mandato = None
    problema: str = ""
    modalita_giusta: bool = True


def _in_distinta(campo):
    """Scadenze già in una distinta non respinta: non si mettono due volte."""
    return VoceDistinta.objects.filter(esito__in=(VoceDistinta.ATTESA, VoceDistinta.PAGATA)).values(campo)


def _coordinate(contatto):
    return CoordinateBancarie.objects.filter(contatto=contatto).first()


def candidati(azienda, tipo):
    if tipo == Distinta.BONIFICI:
        return _da_pagare(azienda)
    return _da_incassare(azienda, tipo)


def _da_pagare(azienda):
    scadenze = (ScadenzaPassiva.objects.filter(fattura__azienda=azienda, pagata=False, fattura__stato=FatturaPassiva.REGISTRATA)
                .exclude(fattura__tipo_documento="TD04").exclude(pk__in=_in_distinta("scadenza_passiva"))
                .select_related("fattura__fornitore").order_by("data", "pk"))
    risultato = []
    for s in scadenze:
        coordinate = _coordinate(s.fattura.fornitore)
        iban = s.iban or (coordinate.iban if coordinate else "")
        c = Candidato(f"p{s.pk}", s, s.fattura, s.fattura.fornitore.nome, s.importo, s.data or s.fattura.data, iban=iban,
                      modalita_giusta=s.modalita in ("", "MP05"))
        if not iban:
            c.problema = "manca l'IBAN del fornitore"
        elif not iban_valido(iban):
            c.problema = "IBAN del fornitore non valido"
        risultato.append(c)
    return risultato


def _da_incassare(azienda, tipo):
    scadenze = (Scadenza.objects.filter(fattura__azienda=azienda, fattura__stato=Fattura.EMESSA, pagata=False)
                .exclude(fattura__tipo=Fattura.NOTA_CREDITO).exclude(pk__in=_in_distinta("scadenza"))
                .select_related("fattura__cliente").order_by("data", "pk"))
    mandati = {}
    if tipo == Distinta.SDD:
        for m in Mandato.objects.filter(azienda=azienda, attivo=True).order_by("-data_firma"):
            mandati.setdefault(m.contatto_id, m)
    risultato = []
    for s in scadenze:
        if s.residuo <= 0:
            continue
        cliente = s.fattura.cliente
        c = Candidato(f"a{s.pk}", s, s.fattura, cliente.nome, s.residuo, s.data, modalita_giusta=s.modalita in MODALITA[tipo])
        if tipo == Distinta.SDD:
            c.mandato = mandati.get(cliente.pk)
            c.iban = c.mandato.iban if c.mandato else ""
            if c.mandato is None:
                c.problema = "il cliente non ha un mandato SDD attivo"
        else:
            coordinate = _coordinate(cliente)
            c.iban = coordinate.iban if coordinate else ""
            if not c.iban:
                c.problema = "manca la banca del cliente (coordinate bancarie)"
            elif not c.iban.startswith("IT"):
                c.problema = "la RiBa va su una banca italiana"
        if c.modalita_giusta or (tipo == Distinta.SDD and c.mandato):      # le altre scadenze non c'entrano
            risultato.append(c)
    return risultato


def _causale(fattura, scadenza):
    return f"Fattura {fattura.numero} del {fattura.data:%d/%m/%Y}" + (f" scad. {scadenza.data:%d/%m/%Y}" if scadenza.data else "")


@transaction.atomic
def crea(azienda, tipo, conto, data, chiavi, utente=None):
    scelti = [c for c in candidati(azienda, tipo) if c.chiave in set(chiavi)]
    if not scelti:
        raise ValidationError("Scegli almeno una scadenza.")
    if problemi := [f"{c.nome}: {c.problema}" for c in scelti if c.problema]:
        raise ValidationError(problemi)
    distinta = Distinta.objects.create(azienda=azienda, tipo=tipo, conto=conto, data=data, utente=utente)
    distinta.identificativo = f"ADB{distinta.pk:07d}{timezone.localtime():%y%m%d%H%M}"
    distinta.save(update_fields=["identificativo"])
    for c in scelti:
        VoceDistinta.objects.create(
            distinta=distinta, scadenza=c.scadenza if tipo != Distinta.BONIFICI else None,
            scadenza_passiva=c.scadenza if tipo == Distinta.BONIFICI else None, mandato=c.mandato, nome=c.nome[:140],
            iban=c.iban, importo=c.importo, data=c.data or data, causale=_causale(c.fattura, c.scadenza)[:140])
    return distinta


def config(conto):
    return ConfigConto.objects.filter(conto=conto).first() or ConfigConto(conto=conto)


def controlli(distinta):
    """Gli errori che impediscono il file."""
    cfg, errori = config(distinta.conto), []
    if not distinta.voci.exists():
        errori.append("La distinta è vuota.")
    if distinta.tipo == Distinta.SDD and not cfg.id_creditore:
        errori.append("Manca l'identificativo del creditore SEPA sul conto (Banca → Conti).")
    if distinta.tipo == Distinta.RIBA:
        if not cfg.codice_sia:
            errori.append("Manca il codice SIA sul conto (Banca → Conti).")
        if not distinta.conto.iban.startswith("IT"):
            errori.append("Le RiBa si presentano da un conto italiano.")
    if distinta.tipo == Distinta.SDD and distinta.data < timezone.localdate() + datetime.timedelta(days=1):
        errori.append("La data di addebito deve essere almeno il giorno lavorativo dopo la presentazione.")
    return errori


def file(distinta):
    """(nome, contenuto in bytes, tipo MIME)."""
    if errori := controlli(distinta):
        raise ValidationError(errori)
    voci = list(distinta.voci.select_related("mandato", "scadenza__fattura__cliente").order_by("data", "pk"))
    cfg = config(distinta.conto)
    if distinta.tipo == Distinta.RIBA:
        def coordinate_cliente(v):
            cliente = v.scadenza.fattura.cliente
            c = _coordinate(cliente)
            iban = c.iban if c else v.iban
            return iban[5:10], iban[10:15], c.banca if c else "", cliente
        testo = riba.genera(distinta, voci, cfg.codice_sia, coordinate_cliente)
        return f"riba-{distinta.identificativo}.txt", testo.encode("ascii"), "text/plain"
    messaggio = sepa.VERSIONI[cfg.versione_sepa][distinta.tipo]
    if distinta.tipo == Distinta.BONIFICI:
        documento = sepa.bonifici(distinta, voci, cfg.versione_sepa)
    else:
        documento = sepa.addebiti(distinta, voci, cfg.versione_sepa, cfg.id_creditore)
    return f"{messaggio}-{distinta.identificativo}.xml", sepa.serializza(documento, messaggio), "application/xml"


def presenta(distinta, data=None):
    if distinta.stato == Distinta.BOZZA:
        distinta.stato, distinta.presentata_il = Distinta.PRESENTATA, data or timezone.localdate()
        distinta.save(update_fields=["stato", "presentata_il"])


def _chiudi_se_finita(distinta):
    if distinta.stato != Distinta.BOZZA and not distinta.voci.filter(esito=VoceDistinta.ATTESA).exists():
        distinta.stato = Distinta.CHIUSA
        distinta.save(update_fields=["stato"])


@transaction.atomic
def pagata(voce, data=None, utente=None):
    """Esito positivo: l'incasso sulla scadenza del cliente, o la scadenza del fornitore pagata."""
    voce = VoceDistinta.objects.select_for_update().select_related("distinta").get(pk=voce.pk)
    if voce.esito == VoceDistinta.PAGATA:
        return voce
    if voce.distinta.stato == Distinta.BOZZA:
        raise ValidationError("Presenta prima la distinta alla banca.")
    data = data or voce.data
    if voce.scadenza_id:
        scadenza = voce.scadenza
        importo = min(voce.importo, scadenza.residuo)
        if importo > 0:
            voce.incasso = operazioni.registra_incasso(scadenza, importo, data, metodo=METODO[voce.distinta.tipo],
                                                       riferimento=f"Distinta {voce.distinta.pk}", utente=utente)
    elif voce.scadenza_passiva_id:
        passive.paga(voce.scadenza_passiva, data)
    voce.esito, voce.esito_il, voce.motivo = VoceDistinta.PAGATA, data, ""
    voce.save(update_fields=["esito", "esito_il", "motivo", "incasso"])
    _chiudi_se_finita(voce.distinta)
    return voce


@transaction.atomic
def insoluta(voce, data=None, motivo=""):
    """Esito negativo (RiBa insoluta, SDD respinto o stornato, bonifico rifiutato): la scadenza torna aperta."""
    voce = VoceDistinta.objects.select_for_update().select_related("distinta").get(pk=voce.pk)
    if voce.distinta.stato == Distinta.BOZZA:
        raise ValidationError("Presenta prima la distinta alla banca.")
    if voce.incasso_id:
        incasso, voce.incasso = voce.incasso, None
        voce.save(update_fields=["incasso"])
        operazioni.annulla_incasso(incasso)
    if voce.scadenza_passiva_id and voce.esito == VoceDistinta.PAGATA:
        s = voce.scadenza_passiva
        s.pagata, s.pagata_il = False, None
        s.save(update_fields=["pagata", "pagata_il"])
        FatturaPassiva.objects.filter(pk=s.fattura_id).update(pagata=False)
    voce.esito, voce.esito_il, voce.motivo = VoceDistinta.INSOLUTA, data or timezone.localdate(), motivo[:120]
    voce.save(update_fields=["esito", "esito_il", "motivo"])
    _chiudi_se_finita(voce.distinta)
    return voce


def tutte_pagate(distinta, data=None, utente=None):
    n = 0
    for v in distinta.voci.filter(esito=VoceDistinta.ATTESA):
        pagata(v, data, utente)
        n += 1
    return n


def elimina(distinta):
    if distinta.stato != Distinta.BOZZA:
        raise ValidationError("Si elimina solo una distinta non ancora presentata.")
    distinta.delete()

