"""Classe ABC dei clienti dal fatturato degli ultimi 12 mesi e segmenti ricalcolati dalle loro regole.
Il fatturato viene dalle fatture emesse (note di credito in meno) se c'è la Fatturazione; senza, ABC e regole sul
fatturato o sugli acquisti non filtrano nessuno."""
import datetime
from decimal import Decimal

from django.apps import apps
from django.db import transaction
from django.db.models import Case, DecimalField, F, Max, Sum, When
from django.utils import timezone

from .models import Contatto, Segmento

SOGLIE = ((Decimal("0.80"), "A"), (Decimal("0.95"), "B"))


def _fatture(azienda_id):
    if not apps.is_installed("fatturazione"):
        return None
    from fatturazione.models import Fattura
    return Fattura.objects.filter(azienda_id=azienda_id, stato=Fattura.EMESSA)


def fatturato(azienda_id, dal):
    """{cliente_id: imponibile dal giorno `dal`}, note di credito in meno."""
    fatture = _fatture(azienda_id)
    if fatture is None:
        return {}
    from fatturazione.models import Fattura
    segno = Case(When(tipo=Fattura.NOTA_CREDITO, then=-F("imponibile")), default=F("imponibile"),
                 output_field=DecimalField(max_digits=14, decimal_places=2))
    return dict(fatture.filter(data__gte=dal).values("cliente_id").annotate(t=Sum(segno)).values_list("cliente_id", "t"))


@transaction.atomic
def classi_abc(azienda_id, oggi=None):
    """Aggiorna fatturato_12_mesi e classe_abc dei contatti dell'azienda. Restituisce {classe: quanti}."""
    oggi = oggi or timezone.localdate()
    totali = {c: t for c, t in fatturato(azienda_id, oggi - datetime.timedelta(days=365)).items() if t and t > 0}
    Contatto.objects.filter(azienda_id=azienda_id).exclude(classe_abc="", fatturato_12_mesi=0).update(classe_abc="", fatturato_12_mesi=0)
    somma, cumulato, conteggi = sum(totali.values(), Decimal(0)), Decimal(0), {"A": 0, "B": 0, "C": 0}
    per_classe = {"A": [], "B": [], "C": []}
    for cliente, t in sorted(totali.items(), key=lambda x: -x[1]):
        prima = cumulato / somma                     # la classe dipende da dove inizia il cliente nella cumulata
        cumulato += t
        classe = next((c for soglia, c in SOGLIE if prima < soglia), "C")
        per_classe[classe].append((cliente, t))
        conteggi[classe] += 1
    da_salvare = []
    for classe, voci in per_classe.items():
        for cliente, t in voci:
            da_salvare.append(Contatto(pk=cliente, classe_abc=classe, fatturato_12_mesi=t))
    Contatto.objects.bulk_update(da_salvare, ["classe_abc", "fatturato_12_mesi"], batch_size=500)
    return conteggi


def candidati(segmento, oggi=None):
    """Il queryset dei contatti che rispettano le regole (senza aggiunti ed esclusi)."""
    oggi = oggi or timezone.localdate()
    qs = Contatto.objects.filter(azienda_id=segmento.azienda_id, attivo=True)
    if segmento.solo_clienti:
        qs = qs.filter(cliente=True)
    if segmento.solo_fornitori:
        qs = qs.filter(fornitore=True)
    if segmento.tipo:
        qs = qs.filter(tipo=segmento.tipo)
    if segmento.pk and segmento.categorie.exists():
        qs = qs.filter(categorie__in=segmento.categorie.all())
    province = [p.strip().upper() for p in segmento.province.split(",") if p.strip()]
    if province:
        qs = qs.filter(provincia__in=province)
    if segmento.nazione:
        qs = qs.filter(nazione=segmento.nazione.upper())
    if segmento.responsabile_id:
        qs = qs.filter(responsabile_id=segmento.responsabile_id)
    if segmento.classi:
        qs = qs.filter(classe_abc__in=list(segmento.classi))
    if segmento.fatturato_minimo is not None:
        qs = qs.filter(fatturato_12_mesi__gte=segmento.fatturato_minimo)
    if segmento.fatturato_massimo is not None:
        qs = qs.filter(fatturato_12_mesi__lte=segmento.fatturato_massimo)
    if segmento.acquisto_entro or segmento.inattivo_da:
        fatture = _fatture(segmento.azienda_id)
        ultime = (dict(fatture.values("cliente_id").annotate(u=Max("data")).values_list("cliente_id", "u"))
                  if fatture is not None else {})
        if segmento.acquisto_entro:
            dal = oggi - datetime.timedelta(days=segmento.acquisto_entro)
            qs = qs.filter(pk__in=[c for c, u in ultime.items() if u >= dal])
        if segmento.inattivo_da:
            dal = oggi - datetime.timedelta(days=segmento.inattivo_da)
            qs = qs.filter(pk__in=[c for c, u in ultime.items() if u < dal])   # hanno comprato, ma non di recente
    return qs.distinct()


def ricalcola_segmento(segmento, oggi=None):
    ids = set(candidati(segmento, oggi).values_list("pk", flat=True))
    ids |= set(segmento.aggiunti.values_list("pk", flat=True))
    ids -= set(segmento.esclusi.values_list("pk", flat=True))
    segmento.membri.set(ids)
    Segmento.objects.filter(pk=segmento.pk).update(numero=len(ids), ricalcolato_il=timezone.now())
    segmento.numero = len(ids)
    return len(ids)


def ricalcola(azienda_id=None):
    """Lavoro notturno: classi ABC, poi i segmenti attivi di ogni azienda."""
    from core.models import Azienda
    aziende = [azienda_id] if azienda_id else list(Azienda.objects.values_list("pk", flat=True))
    totale = 0
    for az in aziende:
        if _fatture(az) is not None:
            classi_abc(az)
        for s in Segmento.objects.filter(azienda_id=az, attivo=True):
            ricalcola_segmento(s)
            totale += 1
    return totale
