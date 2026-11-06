"""Pagine della liquidazione IVA e della LIPE."""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.dashboard import queryset
from fatturazione.commercialista import foglio
from fatturazione.scadenzario import numero_csv
from sdi.models import FatturaPassiva

from . import calcolo, lipe as comunicazione
from .forms import DetraibilitaForm, ManualiForm
from .models import Detraibilita, Liquidazione

VOCI = [("attive", "VP2", "Totale operazioni attive (senza IVA)"), ("passive", "VP3", "Totale operazioni passive (senza IVA)"),
        ("esigibile", "VP4", "IVA esigibile"), ("detratta", "VP5", "IVA detratta"), ("iva_dovuta", "VP6", "IVA dovuta"),
        ("iva_credito", "VP6", "IVA a credito"), ("debito_precedente", "VP7", "Debito del periodo prima, sotto la soglia"),
        ("credito_precedente", "VP8", "Credito del periodo prima"),
        ("credito_anno_precedente", "VP9", "Credito dell'anno prima"), ("versamenti_auto", "VP10", "Versamenti auto UE"),
        ("crediti_imposta", "VP11", "Crediti d'imposta"), ("interessi", "VP12", "Interessi dei trimestrali (1%)"),
        ("acconto", "VP13", "Acconto"), ("da_versare", "VP14", "Importo da versare"), ("a_credito", "VP14", "Importo a credito")]


def _anno(request):
    valore = request.GET.get("anno", "")
    return int(valore) if valore.isdigit() else datetime.date.today().year


def _controlla(periodicita, periodo):
    if periodicita not in (Liquidazione.MENSILE, Liquidazione.TRIMESTRALE) or not 1 <= periodo <= calcolo.ultimo_periodo(periodicita):
        raise Http404


@login_required
@permission_required("iva.view_liquidazione", raise_exception=True)
def liquidazione(request):
    anno = _anno(request)
    periodicita = calcolo.periodicita_di(request.azienda)
    periodi = calcolo.anno(request.azienda, anno, periodicita)
    if request.GET.get("formato") == "csv":
        return _csv(f"liquidazioni-iva-{anno}.csv", periodi)
    oggi = datetime.date.today()
    return render(request, "iva/liquidazione.html", {
        "anno": anno, "anni": range(oggi.year, oggi.year - 6, -1), "periodi": list(reversed(periodi)),
        "periodicita": periodicita, "trimestrale": periodicita == Liquidazione.TRIMESTRALE})


def _csv(nome, periodi):
    risposta = HttpResponse(_foglio(periodi), content_type="text/csv; charset=utf-8")
    risposta["Content-Disposition"] = f'attachment; filename="{nome}"'
    return risposta


def _foglio(periodi):
    return foglio(["Periodo"] + [f"{codice} {etichetta}" for _, codice, etichetta in VOCI] + ["Stato", "Versata il"],
                  [[r.nome] + [numero_csv(getattr(r, nome)) for nome, _, _ in VOCI]
                   + ["chiusa" if r.da_chiusura else "aperta",
                      r.liquidazione.versata_il.strftime("%d/%m/%Y") if r.liquidazione and r.liquidazione.versata_il else ""]
                   for r in periodi])


@login_required
@permission_required("iva.view_liquidazione", raise_exception=True)
def periodo(request, anno, periodicita, periodo):
    _controlla(periodicita, periodo)
    azienda = request.azienda
    liq = Liquidazione.objects.filter(azienda=azienda, anno=anno, periodicita=periodicita, periodo=periodo).first()
    puo = request.user.has_perm("iva.change_liquidazione")
    form = ManualiForm(instance=liq or Liquidazione(azienda=azienda, anno=anno, periodicita=periodicita, periodo=periodo))
    if request.method == "POST":
        if not puo:
            raise Http404
        if liq and liq.chiusa:
            messages.error(request, "La liquidazione è chiusa: riaprila per cambiarla.")
            return redirect("iva:periodo", anno, periodicita, periodo)
        form = ManualiForm(request.POST, instance=form.instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Liquidazione aggiornata.")
            return redirect("iva:periodo", anno, periodicita, periodo)
    r = calcolo.liquida(azienda, anno, periodicita, periodo)
    if r.calcolo is None:
        r.calcolo = calcolo.calcola(azienda, anno, periodicita, periodo)
    trimestre = (periodo - 1) // 3 + 1 if periodicita == Liquidazione.MENSILE else periodo
    ultimo_del_trimestre = periodicita == Liquidazione.TRIMESTRALE or periodo % 3 == 0
    return render(request, "iva/periodo.html", {
        "r": r, "c": r.calcolo, "liq": liq, "form": form, "puo": puo, "cambiati": calcolo.cambiati(r),
        "voci": [(codice, etichetta, getattr(r, nome), nome) for nome, codice, etichetta in VOCI],
        "scadenza": r.scadenza, "soglia": calcolo.soglia(), "trimestre": trimestre,
        "bollo": calcolo.bollo_trimestre(azienda, anno, trimestre) if ultimo_del_trimestre else None,
        "elenco_url": f"?anno={anno}"})


def _liq(request, anno, periodicita, periodo):
    _controlla(periodicita, periodo)
    return Liquidazione.objects.filter(azienda=request.azienda, anno=anno, periodicita=periodicita, periodo=periodo).first()


@login_required
@permission_required("iva.change_liquidazione", raise_exception=True)
@require_POST
def chiudi(request, anno, periodicita, periodo):
    _controlla(periodicita, periodo)
    if periodo > 1:
        prima = _liq(request, anno, periodicita, periodo - 1)
        if prima is None or not prima.chiusa:
            messages.error(request, "Chiudi prima il periodo precedente: il suo credito o debito entra in questo.")
            return redirect("iva:periodo", anno, periodicita, periodo)
    calcolo.chiudi(request.azienda, anno, periodicita, periodo, request.user)
    messages.success(request, "Liquidazione chiusa: i numeri restano questi anche se i registri cambiano.")
    return redirect("iva:periodo", anno, periodicita, periodo)


@login_required
@permission_required("iva.change_liquidazione", raise_exception=True)
@require_POST
def riapri(request, anno, periodicita, periodo):
    liq = _liq(request, anno, periodicita, periodo)
    dopo = _liq(request, anno, periodicita, periodo + 1) if periodo < calcolo.ultimo_periodo(periodicita) else None
    if dopo is not None and dopo.chiusa:
        messages.error(request, "Riapri prima il periodo successivo, che usa i numeri di questo.")
    elif liq is not None:
        liq.chiusa, liq.dati = False, {}
        liq.save(update_fields=["chiusa", "dati"])
        messages.success(request, "Liquidazione riaperta: si ricalcola dai registri.")
    return redirect("iva:periodo", anno, periodicita, periodo)


@login_required
@permission_required("iva.change_liquidazione", raise_exception=True)
@require_POST
def versata(request, anno, periodicita, periodo):
    liq = _liq(request, anno, periodicita, periodo)
    if liq is None or not liq.chiusa:
        messages.error(request, "Chiudi la liquidazione prima di segnarla come versata.")
    else:
        try:
            liq.versata_il = datetime.date.fromisoformat(request.POST.get("data", "")) if request.POST.get("data") else None
        except ValueError:
            messages.error(request, "Data non valida.")
        else:
            liq.save(update_fields=["versata_il"])
            messages.success(request, "Versamento segnato." if liq.versata_il else "Versamento tolto.")
    return redirect("iva:periodo", anno, periodicita, periodo)


@login_required
@permission_required("iva.view_liquidazione", raise_exception=True)
def lipe(request):
    oggi = datetime.date.today()
    anno = _anno(request)
    valore = request.GET.get("trimestre", "")
    trimestre = int(valore) if valore in ("1", "2", "3", "4") else max((oggi.month - 1) // 3, 1)
    nome, xml, errori, avvisi = comunicazione.genera(request.azienda, anno, trimestre)
    if request.GET.get("scarica") and xml:
        risposta = HttpResponse(xml, content_type="application/xml")
        risposta["Content-Disposition"] = f'attachment; filename="{nome}"'
        return risposta
    _, voci = comunicazione.risultati(request.azienda, anno, trimestre)
    return render(request, "iva/lipe.html", {
        "anno": anno, "anni": range(oggi.year, oggi.year - 3, -1), "trimestre": trimestre, "errori": errori,
        "avvisi": avvisi, "voci": voci, "nome": nome, "xml": xml.decode() if xml else "",
        "scadenza": comunicazione.SCADENZE[trimestre]})


@login_required
@permission_required("iva.change_detraibilita", raise_exception=True)
@require_POST
def detraibilita(request, pk):
    fattura = get_object_or_404(queryset(request, FatturaPassiva), pk=pk)
    voce = Detraibilita.objects.filter(fattura=fattura).first() or Detraibilita(fattura=fattura)
    form = DetraibilitaForm(request.POST, instance=voce)
    if form.is_valid():
        chiusa = Liquidazione.objects.filter(azienda=fattura.azienda, anno=fattura.registrata_il.year, chiusa=True).exists() \
            if fattura.registrata_il else False
        form.save()
        messages.success(request, f"IVA detraibile al {voce.percentuale:g}%."
                         + (" Le liquidazioni chiuse dell'anno non cambiano finché non le riapri." if chiusa else ""))
    else:
        messages.error(request, " ".join(e for errori in form.errors.values() for e in errori))
    return redirect("sdi:passive_dettaglio", fattura.pk)
