"""Importa i movimenti e li abbina alle scadenze. Un abbinamento è sempre confermato da qualcuno; le uniche scritture fuori da qui
sono gli incassi veri di Fatturazione e le scadenze dei fornitori: nessuna registrazione contabile, che resta al commercialista."""
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from fatturazione import operazioni as fatture
from fatturazione.models import Fattura, Incasso, Scadenza
from sdi import passive
from sdi.models import ScadenzaPassiva

from . import estratti
from .models import Abbinamento, Conto, Importazione, MovimentoBanca, normalizza_iban

METODI = {"MP12": "riba", "MP19": "sdd", "MP20": "sdd", "MP21": "sdd", "MP02": "assegno", "MP03": "assegno", "MP08": "carta", "MP01": "contanti"}
PUNTI_NUMERO, PUNTI_IMPORTO, PUNTI_PIVA, PUNTI_NOME = 60, 30, 40, 20
PUNTI_MINIMI = 20
SICURO = PUNTI_NUMERO + PUNTI_IMPORTO
MASSIMO_SICURI = 200


# ---------- importazione

@transaction.atomic
def importa(conto, contenuto, nome_file="", utente=None):
    """Tutto o niente; le righe già presenti si contano, non si duplicano."""
    estratto = estratti.leggi(contenuto, nome_file)
    if estratto.iban and estratto.iban != normalizza_iban(conto.iban):
        raise estratti.EstrattoNonValido(f"Questo estratto è del conto {estratto.iban}, non di «{conto}»: controlla il conto scelto.")
    if estratto.coordinate and conto.iban.startswith("IT") and len(conto.iban) == 27:
        abi, cab, numero_conto = estratto.coordinate
        if (abi, cab, numero_conto.lstrip("0")) != (conto.iban[5:10], conto.iban[10:15], conto.iban[15:27].lstrip("0")):
            raise estratti.EstrattoNonValido(f"Questo estratto è del conto {numero_conto.lstrip('0')} (ABI {abi}, CAB {cab}), "
                                             f"non di «{conto}»: controlla il conto scelto.")
    if not estratto.righe and not estratto.scartate:
        raise estratti.EstrattoNonValido("Nel file non c'è nessun movimento.")
    esame = Importazione.objects.create(azienda=conto.azienda, conto=conto, nome_file=(nome_file or "")[:200], formato=estratto.formato,
                                        scartati=estratto.scartate, utente=utente)
    impronte = estratti.impronte(estratto.righe)
    presenti = set(MovimentoBanca.objects.filter(conto=conto, impronta__in=impronte).values_list("impronta", flat=True))
    nuovi = []
    for riga, impronta in zip(estratto.righe, impronte):
        if impronta in presenti:
            esame.doppi += 1
            continue
        nuovi.append(MovimentoBanca(azienda=conto.azienda, conto=conto, importazione=esame, data=riga.data, valuta=riga.valuta, importo=riga.importo,
                               descrizione=riga.descrizione, controparte=riga.controparte[:200], iban_controparte=riga.iban_controparte[:34],
                               riferimento=riga.riferimento[:120], impronta=impronta))
    MovimentoBanca.objects.bulk_create(nuovi)
    esame.nuovi = len(nuovi)
    esame.save(update_fields=["nuovi", "doppi"])
    if estratto.saldo is not None and (conto.saldo_al is None or (estratto.saldo_al and estratto.saldo_al >= conto.saldo_al)):
        conto.saldo, conto.saldo_al = estratto.saldo, estratto.saldo_al
        conto.save(update_fields=["saldo", "saldo_al"])
    return esame


# ---------- suggerimenti

@dataclass
class Proposta:
    scadenza: object
    passiva: bool
    punti: int = 0
    motivi: list = field(default_factory=list)
    punti_storia: int = 0          # quelli dagli abbinamenti già confermati: non contano per «sicura»

    @property
    def residuo(self):
        return self.scadenza.importo if self.passiva else self.scadenza.residuo

    @property
    def documento(self):
        return self.scadenza.fattura

    @property
    def controparte(self):
        return self.scadenza.fattura.fornitore if self.passiva else self.scadenza.fattura.cliente

    @property
    def chiave(self):
        return f"{'p' if self.passiva else 'a'}{self.scadenza.pk}"


def aperte_attive(azienda):
    return list(Scadenza.objects.filter(fattura__azienda=azienda, fattura__stato=Fattura.EMESSA, pagata=False).select_related("fattura__cliente").order_by("data", "pk"))


def aperte_passive(azienda):
    return list(ScadenzaPassiva.objects.filter(fattura__azienda=azienda, pagata=False).select_related("fattura__fornitore").order_by("data", "pk"))


def _numero_nel_testo(numero, testo):
    """12/2026 si trova anche scritto 12-2026 o 12 2026, ma non dentro 112/2026 o 12/20265."""
    if not numero:
        return False
    parti = [re.escape(p) for p in re.split(r"[/\-\s]+", numero) if p]
    return bool(parti) and re.search(r"(?<![\w/])" + r"[/\-\s.]*".join(parti) + r"(?![\w/])", testo, re.I) is not None


def _nome_nel_testo(nome, testo):
    parole = [p for p in re.findall(r"[^\W\d_]{3,}", nome.lower()) if p not in {"srl", "spa", "snc", "sas", "studio", "societa", "società"}]
    return bool(parole) and all(re.search(rf"\b{re.escape(p)}\b", testo.lower()) for p in parole[:2])


def _valuta(movimento, scadenza, passiva, storia=None):
    proposta = Proposta(scadenza, passiva)
    documento, chi = proposta.documento, proposta.controparte
    testo = f"{movimento.descrizione} {movimento.controparte}"
    if _numero_nel_testo(documento.numero, testo):
        proposta.punti += PUNTI_NUMERO
        proposta.motivi.append(f"Numero {documento.numero} nella causale")
    if abs(movimento.importo) == proposta.residuo:
        proposta.punti += PUNTI_IMPORTO
        proposta.motivi.append("Stesso importo")
    if chi.partita_iva and chi.partita_iva in testo:
        proposta.punti += PUNTI_PIVA
        proposta.motivi.append("Partita IVA nella causale")
    if _nome_nel_testo(chi.nome, testo):
        proposta.punti += PUNTI_NOME
        proposta.motivi.append(f"Nome di {chi.nome}")
    if storia is not None and (indizi := storia.indizi(movimento, chi.pk)):
        punti, motivo = max(indizi)                  # l'indizio più forte, non la somma: la storia aiuta, non decide
        proposta.punti += punti
        proposta.punti_storia = punti
        proposta.motivi.append(motivo)
    return proposta


def proposte(movimento, attive, da_pagare, massimo=4, storia=None):
    """Le scadenze più probabili per il movimento; con `storia` (memoria.di) contano anche gli abbinamenti già confermati."""
    if movimento.importo > 0:
        candidati = [_valuta(movimento, s, False, storia) for s in attive]
    else:
        candidati = [_valuta(movimento, s, True, storia) for s in da_pagare]
    buoni = [c for c in candidati if c.punti >= PUNTI_MINIMI]
    return sorted(buoni, key=lambda c: (-c.punti, c.scadenza.data or timezone.localdate()))[:massimo]


def e_sicura(lista):
    """Numero e importo tornano, e nessun'altra scadenza è altrettanto buona. Quello imparato dalla storia non conta:
    da solo non fa mai abbinare in automatico."""
    certi = sorted((p.punti - p.punti_storia for p in lista), reverse=True)
    return bool(certi) and certi[0] >= SICURO and (len(certi) == 1 or certi[1] < SICURO)


# ---------- abbinare

def _aggiorna_stato(movimento):
    abbinato = movimento.abbinato
    if abbinato <= 0:
        if movimento.stato != MovimentoBanca.IGNORATO:
            movimento.stato = MovimentoBanca.DA_ABBINARE
    else:
        movimento.stato = MovimentoBanca.ABBINATO if abbinato >= abs(movimento.importo) else MovimentoBanca.PARZIALE
    movimento.save(update_fields=["stato"])


def _passiva_cambiata(fattura):
    fattura.pagata = not fattura.scadenze.filter(pagata=False).exists()
    fattura.save(update_fields=["pagata"])


@transaction.atomic
def abbina(movimento, chiavi, utente=None):
    """Copre le scadenze scelte, nell'ordine, finché il movimento basta. Un residuo resta da abbinare, mai un incasso in più."""
    movimento = MovimentoBanca.objects.select_for_update().select_related("conto").get(pk=movimento.pk)
    if movimento.stato == MovimentoBanca.IGNORATO:
        raise ValidationError("Questo movimento è ignorato: ripristinalo prima di abbinarlo.")
    resto = movimento.da_coprire
    if resto <= 0:
        raise ValidationError("Questo movimento è già tutto abbinato.")
    if not chiavi:
        raise ValidationError("Scegli almeno una scadenza.")
    fatti = []
    for chiave in chiavi:
        if resto <= 0:
            break
        tipo, numero = chiave[:1], chiave[1:]
        if not numero.isdigit() or tipo not in ("a", "p") or (tipo == "a") != (movimento.importo > 0):
            raise ValidationError("Una delle scadenze scelte non va bene per questo movimento.")
        if tipo == "a":
            fatti.append(_su_attiva(movimento, int(numero), resto, utente))
        else:
            fatti.append(_su_passiva(movimento, int(numero), resto, utente))
        resto -= fatti[-1].importo
    _aggiorna_stato(movimento)
    return fatti


def _su_attiva(movimento, pk, resto, utente):
    scadenza = Scadenza.objects.filter(pk=pk, fattura__azienda=movimento.azienda, fattura__stato=Fattura.EMESSA, pagata=False).first()
    if scadenza is None:
        raise ValidationError("Una scadenza scelta non è più aperta: ricarica la pagina.")
    quota = min(resto, scadenza.residuo)
    riferimento = (movimento.riferimento or movimento.descrizione)[:120]
    incasso = fatture.registra_incasso(scadenza, quota, movimento.data, METODI.get(scadenza.modalita, "bonifico"), Incasso.INCASSO, riferimento, utente)
    return Abbinamento.objects.create(movimento=movimento, incasso=incasso, importo=quota, utente=utente)


def _su_passiva(movimento, pk, resto, utente):
    """Le scadenze dei fornitori non hanno pagamenti parziali: serve l'importo per intero."""
    scadenza = ScadenzaPassiva.objects.select_for_update().select_related("fattura").filter(pk=pk, fattura__azienda=movimento.azienda, pagata=False).first()
    if scadenza is None:
        raise ValidationError("Una scadenza scelta non è più aperta: ricarica la pagina.")
    if resto < scadenza.importo:
        raise ValidationError(f"Il movimento non copre tutta la scadenza da {scadenza.importo} €: va pagata per intero.")
    passive.paga(scadenza, movimento.data)
    return Abbinamento.objects.create(movimento=movimento, scadenza_passiva=scadenza, importo=scadenza.importo, utente=utente)


@transaction.atomic
def annulla(abbinamento):
    """Toglie anche l'incasso o riapre la scadenza: come se non fosse mai stato abbinato."""
    if abbinamento.incasso_id:
        fatture.annulla_incasso(abbinamento.incasso)        # l'abbinamento se ne va con lui, e il segnale aggiorna il movimento
    elif abbinamento.id_documento:                          # un altro documento (es. un rimborso): resta com'è
        abbinamento.delete()
    else:
        scadenza = abbinamento.scadenza_passiva
        scadenza.pagata, scadenza.pagata_il = False, None
        scadenza.save(update_fields=["pagata", "pagata_il"])
        _passiva_cambiata(scadenza.fattura)
        abbinamento.delete()


def candidati_uscita(azienda, importo, data=None, giorni=45):
    """I movimenti in uscita dell'azienda che potrebbero pagare `importo`: non ignorati, con almeno quel residuo, entro
    `giorni` dalla data; prima quelli dell'importo esatto e più vicini alla data."""
    from datetime import timedelta

    from django.utils import timezone
    data = data or timezone.localdate()
    movimenti = (MovimentoBanca.objects.filter(azienda=azienda, importo__lt=0, data__range=(data - timedelta(days=giorni), data + timedelta(days=giorni)))
                 .exclude(stato__in=(MovimentoBanca.IGNORATO, MovimentoBanca.ABBINATO)).select_related("conto"))
    adatti = [m for m in movimenti if m.da_coprire >= importo]
    return sorted(adatti, key=lambda m: (abs(m.importo) != importo, abs((m.data - data).days)))[:10]


@transaction.atomic
def abbina_documento(movimento, documento, importo, utente=None):
    """Il movimento salda `importo` di un documento di un altro modulo (es. il rimborso di una nota spese)."""
    from django.contrib.contenttypes.models import ContentType
    movimento = MovimentoBanca.objects.select_for_update().get(pk=movimento.pk)
    if movimento.stato == MovimentoBanca.IGNORATO:
        raise ValidationError("Questo movimento è ignorato: ripristinalo prima di abbinarlo.")
    if importo <= 0 or movimento.da_coprire < importo:
        raise ValidationError(f"Il movimento non copre {importo} €.")
    a = Abbinamento.objects.create(movimento=movimento, importo=importo, utente=utente,
                                   tipo_documento=ContentType.objects.get_for_model(documento), id_documento=documento.pk)
    _aggiorna_stato(movimento)
    return a


def abbinamenti_di(documento):
    """Gli abbinamenti che saldano un documento di un altro modulo."""
    from django.contrib.contenttypes.models import ContentType
    return Abbinamento.objects.filter(tipo_documento=ContentType.objects.get_for_model(documento), id_documento=documento.pk).select_related("movimento__conto")


def abbinamento_tolto(sender, instance, **kwargs):
    movimento = MovimentoBanca.objects.filter(pk=instance.movimento_id).first()
    if movimento:
        _aggiorna_stato(movimento)


def abbina_i_sicuri(azienda, utente=None, conto=None):
    """Solo quando l'utente lo chiede: i movimenti con numero e importo giusti e un'unica scadenza possibile."""
    movimenti = MovimentoBanca.objects.filter(azienda=azienda, stato=MovimentoBanca.DA_ABBINARE)
    if conto:
        movimenti = movimenti.filter(conto=conto)
    attive, da_pagare, fatti = aperte_attive(azienda), aperte_passive(azienda), 0
    usate = set()
    for movimento in movimenti.order_by("data", "pk")[:MASSIMO_SICURI]:
        lista = [p for p in proposte(movimento, attive, da_pagare) if p.chiave not in usate]
        if not e_sicura(lista):
            continue
        try:
            abbina(movimento, [lista[0].chiave], utente)
        except ValidationError:
            continue
        usate.add(lista[0].chiave)
        fatti += 1
    return fatti


@transaction.atomic
def ignora(movimento):
    if movimento.abbinamenti.exists():
        raise ValidationError("Il movimento è abbinato: togli prima l'abbinamento.")
    movimento.stato = MovimentoBanca.IGNORATO
    movimento.save(update_fields=["stato"])


@transaction.atomic
def ripristina(movimento):
    movimento.stato = MovimentoBanca.DA_ABBINARE
    movimento.save(update_fields=["stato"])
    _aggiorna_stato(movimento)
