"""Le pagine di Analisi: le schede della dashboard con i loro widget, i grafici salvati e le vie per salvarne di nuovi
(da un grafico dell'assistente, dalla vista Grafico di un modulo)."""
import json

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.http import Http404, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from core import dashboard as dash
from core.registry import modules
from core.viste import interroga
from core.viste.interroga import ErroreInterrogazione

from . import motore
from .models import Grafico, Pagina

VISTA, MODIFICA, CONDIVIDI = "grafici.view_pagina", "grafici.change_pagina", "grafici.condividi_pagina"


# ---------- pagine ----------

def _mia(request, pk):
    return get_object_or_404(Pagina, pk=pk, utente=request.user)


def _visibile(request, pk):
    p = get_object_or_404(Pagina.objects.select_related("utente"), pk=pk)
    if p.utente_id != request.user.id and not p.condivisa:
        raise Http404
    return p


def _app(request, app):
    """La scheda dell'app per chi guarda: creata al primo accesso, così ha un layout e un titolo suoi."""
    info = next((a for a in motore.app_con_indicatori(request.user) if a["slug"] == app), None)
    if info is None:
        raise Http404
    icona = info.get("icon") or "zap"
    p, _ = Pagina.objects.get_or_create(utente=request.user, app=app, defaults={
        "titolo": info["label"], "icona": "bar-chart" if "/" in icona else icona})
    return p, info


def _torna(request, p):
    return redirect("grafici:pagina_app", app=p.app) if p.app else redirect("grafici:pagina", pk=p.pk)


def _rendi(request, p, info=None):
    widget, libreria = motore.catalogo(p, request)
    visibili, nascosti = dash.disponi(p.layout, widget)
    mio = p.utente_id == request.user.id
    return render(request, "grafici/pagina.html", {
        "pagina": p, "info_app": info, "widget": visibili, "nascosti": nascosti + libreria, "mio": mio,
        "personalizzata": bool(p.layout), "icone": motore.ICONE,
        "url_layout": reverse("grafici:layout_app", args=[p.app]) if p.app else reverse("grafici:layout", args=[p.pk]),
        "contesto_ada": motore.contesto_ada(p, visibili), "scheda_attiva": p.chiave,
        "sorelle": [x for x in Pagina.objects.filter(utente=request.user, app="") if x.pk != p.pk] if mio and not p.app else [],
        "ai": motore._ai_disponibile()})


@login_required
@permission_required(VISTA)
def pagina(request, pk):
    return _rendi(request, _visibile(request, pk))


@login_required
@permission_required(VISTA)
def pagina_app(request, app):
    p, info = _app(request, app)
    return _rendi(request, p, info)


@login_required
@permission_required(VISTA)
def pagine(request):
    """Gestione: le pagine dell'utente, quelle condivise con lui, le schede delle app nascoste e i grafici in libreria."""
    mie = list(Pagina.objects.filter(utente=request.user).prefetch_related("grafici"))
    nascoste = {p.app for p in mie if p.app and p.nascosta}
    return render(request, "grafici/pagine.html", {
        "libere": [p for p in mie if not p.app], "app_pagine": [p for p in mie if p.app],
        "condivise": Pagina.objects.filter(condivisa=True).exclude(utente=request.user).select_related("utente"),
        "app_nascoste": [a for a in motore.app_con_indicatori(request.user) if a["slug"] in nascoste],
        "libreria": Grafico.objects.filter(utente=request.user, pagina__isnull=True),
        "destinazioni": motore.destinazioni(request), "icone": motore.ICONE})


def _layout(request, p):
    try:
        salvato = motore.salva_layout(p, json.loads(request.body or b"{}"), request)
    except (ValueError, TypeError):
        return JsonResponse({"errore": "disposizione non valida"}, status=400)
    return JsonResponse({"ok": True, **salvato})


@login_required
@permission_required(MODIFICA)
@require_POST
def layout(request, pk):
    return _layout(request, _mia(request, pk))


@login_required
@permission_required(MODIFICA)
@require_POST
def layout_app(request, app):
    return _layout(request, _app(request, app)[0])


@login_required
@permission_required("grafici.add_pagina")
@require_POST
def nuova(request):
    titolo = request.POST.get("titolo", "").strip()[:100] or "Nuova pagina"
    icona = request.POST.get("icona", "bar-chart")
    ordine = (Pagina.objects.filter(utente=request.user, app="").aggregate(m=Max("ordine"))["m"] or 0) + 1
    p = Pagina.objects.create(utente=request.user, titolo=titolo, ordine=ordine,
                              icona=icona if icona in dict(motore.ICONE) else "bar-chart")
    messages.success(request, f"Pagina «{p.titolo}» creata: aggiungi i grafici da Ada, dalle viste Grafico o dalla libreria.")
    return redirect("grafici:pagina", pk=p.pk)


@login_required
@permission_required(MODIFICA)
@require_POST
def modifica(request, pk):
    p = _mia(request, pk)
    titolo = request.POST.get("titolo", "").strip()[:100]
    if titolo:
        p.titolo = titolo
    icona = request.POST.get("icona")
    if icona in dict(motore.ICONE):
        p.icona = icona
    p.save(update_fields=["titolo", "icona", "aggiornata"])
    return _torna(request, p)


@login_required
@permission_required("grafici.delete_pagina")
@require_POST
def elimina(request, pk):
    p = _mia(request, pk)
    if p.app:
        raise PermissionDenied("La scheda di un'app si nasconde, non si elimina.")
    n = p.grafici.update(pagina=None)                   # i grafici restano in libreria
    p.delete()
    messages.success(request, f"Pagina eliminata" + (f": {n} grafic{'o' if n == 1 else 'i'} in libreria." if n else "."))
    return redirect("core:dashboard")


@login_required
@permission_required(CONDIVIDI)
@require_POST
def condividi(request, pk):
    p = _mia(request, pk)
    if p.app:
        raise PermissionDenied("La scheda di un'app è personale.")
    p.condivisa = not p.condivisa
    p.save(update_fields=["condivisa", "aggiornata"])
    messages.success(request, "Pagina condivisa con tutta l'azienda: ognuno vede i dati che i suoi permessi gli consentono."
                     if p.condivisa else "La pagina è di nuovo solo tua.")
    return _torna(request, p)


@login_required
@permission_required(MODIFICA)
@require_POST
def sposta(request, pk):
    p = _mia(request, pk)
    direzione = -1 if request.POST.get("direzione") == "-1" else 1
    libere = list(Pagina.objects.filter(utente=request.user, app="").order_by("ordine", "pk"))
    for i, x in enumerate(libere):                       # ordini tutti distinti prima di scambiare
        if x.ordine != i + 1:
            Pagina.objects.filter(pk=x.pk).update(ordine=i + 1)
            x.ordine = i + 1
    i = next(k for k, x in enumerate(libere) if x.pk == p.pk)
    j = i + direzione
    if 0 <= j < len(libere):
        Pagina.objects.filter(pk=libere[i].pk).update(ordine=libere[j].ordine)
        Pagina.objects.filter(pk=libere[j].pk).update(ordine=libere[i].ordine)
    return _torna(request, p)


@login_required
@permission_required(MODIFICA)
@require_POST
def ripristina(request, pk):
    p = _mia(request, pk)
    p.layout = {}
    p.save(update_fields=["layout", "aggiornata"])
    messages.success(request, "Disposizione riportata a quella di partenza.")
    return _torna(request, p)


@login_required
@permission_required(VISTA)
@require_POST
def aggiorna_pagina(request, pk):
    p = _visibile(request, pk)
    errori = 0
    for g in p.grafici.filter(utente=request.user):
        errori += bool(motore.aggiorna(g, request, forza=True)[1])
    messages.success(request, "Grafici ricalcolati con i dati di adesso." + (f" {errori} non calcolabili." if errori else ""))
    return _torna(request, p)


@login_required
@permission_required(MODIFICA)
@require_POST
def nascondi_app(request, app):
    p, info = _app(request, app)
    p.nascosta = not p.nascosta
    p.save(update_fields=["nascosta", "aggiornata"])
    if p.nascosta:
        messages.success(request, f"Scheda «{info['label']}» nascosta: la ritrovi in Analisi → Pagine.")
        return redirect("core:dashboard")
    return redirect("grafici:pagina_app", app=app)


# ---------- grafici ----------

def _grafico_visibile(request, pk):
    g = get_object_or_404(Grafico.objects.select_related("pagina"), pk=pk)
    if g.utente_id != request.user.id and not (g.pagina and g.pagina.condivisa):
        raise Http404
    return g


def _mio_grafico(request, pk):
    return get_object_or_404(Grafico, pk=pk, utente=request.user)


@login_required
@permission_required("grafici.view_grafico")
def grafico(request, pk):
    g = _grafico_visibile(request, pk)
    w = motore.widget_salvato(g, request, forza=bool(request.GET.get("aggiorna")))
    return render(request, "grafici/grafico.html", {
        "g": g, "w": w, "mio": w["mio"], "tipi": motore.TIPI_SCAMBIABILI, "destinazioni": motore.destinazioni(request, g.vista),
        "contesto_ada": {"pagina": f"Grafico: {g.titolo}", "query": w["sotto"], "tipo": w["serie"]["tipo"], "dati": w["serie"]["righe"],
                         **({"previsione": w["serie"]["futuro"]} if w["serie"].get("futuro") else {})},
        "scheda_attiva": g.pagina.chiave if g.pagina else "", "ai": motore._ai_disponibile(),
        "destinazione_attuale": (f"app:{g.pagina.app}" if g.pagina.app else str(g.pagina.pk)) if g.pagina else ""})


@login_required
@permission_required("grafici.view_grafico")
@require_POST
def grafico_aggiorna(request, pk):
    g = _grafico_visibile(request, pk)
    w = motore.widget_salvato(g, request, forza=True)
    if request.headers.get("HX-Request"):
        return render(request, "grafici/_widget.html", {"w": w, "mio": w["mio"]})
    return redirect("grafici:grafico", pk=pk)


@login_required
@permission_required("grafici.change_grafico")
@require_POST
def grafico_tipo(request, pk):
    g = _mio_grafico(request, pk)
    tipo = request.POST.get("tipo", "")
    if g.tipo not in Grafico.INTERCAMBIABILI or tipo not in Grafico.INTERCAMBIABILI:
        return JsonResponse({"errore": "tipo non ammesso per questo grafico"}, status=400)
    g.tipo = tipo
    g.save(update_fields=["tipo", "modificato"])
    if request.headers.get("HX-Request") or request.headers.get("Accept", "").startswith("application/json"):
        return JsonResponse({"ok": True, "tipo": tipo})
    return redirect("grafici:grafico", pk=pk)


def _destinazione(request, valore, titolo_nuova=""):
    """La pagina scelta in un form di salvataggio: id di una pagina propria, «app:slug», «nuova» o vuoto (libreria)."""
    valore = (valore or "").strip()
    if not valore:
        return None
    if valore == "nuova":
        ordine = (Pagina.objects.filter(utente=request.user, app="").aggregate(m=Max("ordine"))["m"] or 0) + 1
        return Pagina.objects.create(utente=request.user, titolo=(titolo_nuova or "").strip()[:100] or "Nuova pagina", ordine=ordine)
    if valore.startswith("app:"):
        return _app(request, valore[4:])[0]
    if valore.isdigit():
        return _mia(request, int(valore))
    raise Http404


@login_required
@permission_required("grafici.change_grafico")
@require_POST
def grafico_modifica(request, pk):
    g = _mio_grafico(request, pk)
    titolo = request.POST.get("titolo", "").strip()[:200]
    if titolo:
        g.titolo = titolo
    if "destinazione" in request.POST:
        g.pagina = _destinazione(request, request.POST["destinazione"], request.POST.get("titolo_nuova"))
    ogni = request.POST.get("aggiorna_ogni", "")
    if ogni.isdigit():
        g.aggiorna_ogni = min(int(ogni), 24 * 30)
    g.save()
    messages.success(request, "Grafico aggiornato.")
    return redirect("grafici:grafico", pk=pk)


@login_required
@permission_required("grafici.delete_grafico")
@require_POST
def grafico_elimina(request, pk):
    g = _mio_grafico(request, pk)
    p = g.pagina
    g.delete()
    messages.success(request, f"Grafico «{g.titolo}» eliminato.")
    return _torna(request, p) if p else redirect("grafici:pagine")


@login_required
@permission_required("grafici.view_grafico")
def grafico_csv(request, pk):
    g = _grafico_visibile(request, pk)
    dati, errore = motore.aggiorna(g, request, forza=bool(request.GET.get("oggi")))
    if errore and not dati:
        return HttpResponse(errore, status=409, content_type="text/plain; charset=utf-8")
    risposta = HttpResponse(motore.csv_di(g, dati), content_type="text/csv; charset=utf-8")
    risposta["Content-Disposition"] = f'attachment; filename="{slugify(g.titolo) or "grafico"}.csv"'
    return risposta


# ---------- salvare da altrove ----------

@login_required
@permission_required("grafici.add_grafico")
@require_POST
def salva_da_artifact(request):
    """Un grafico dell'assistente diventa un grafico salvato: stessa specifica, ricalcolabile da qui in avanti."""
    if not motore._ai_disponibile():
        raise Http404
    Artifact = apps.get_model("ai", "Artifact")
    a = get_object_or_404(Artifact, pk=request.POST.get("artifact"), utente=request.user, tipo="grafico")
    tipo = a.spec.get("grafico", Grafico.BARRE)
    spec = {k: v for k, v in a.spec.items() if k not in ("tipo", "grafico")}
    g = Grafico.objects.create(
        utente=request.user, pagina=_destinazione(request, request.POST.get("destinazione"), request.POST.get("titolo_nuova")),
        titolo=a.titolo, tipo=tipo if tipo in dict(Grafico.TIPI) else Grafico.BARRE, spec=spec, dati=a.dati,
        aggiornato=a.aggiornato or a.creato, origine=Grafico.CHAT,
        origine_url=reverse("ai:conversazione", args=[a.conversazione_id]) if a.conversazione_id else "")
    return render(request, "grafici/_salvato.html", {"g": g})


@login_required
@permission_required("grafici.add_grafico")
@require_POST
def salva_da_vista(request):
    """La vista Grafico di un modulo, con i filtri del momento, diventa un grafico salvato."""
    nome = request.POST.get("vista", "")
    try:
        vista = interroga.vista_per_nome(nome, request)
    except ErroreInterrogazione:
        raise Http404
    tipo = request.POST.get("tipo", Grafico.BARRE)
    parametri = QueryDict(request.POST.get("filtri", ""))
    lista = {k: v for k, v in parametri.items() if (k == "q" or k.startswith("f_")) and v != ""}
    spec = {"vista": nome, "per": request.POST.get("per", ""), "misura": request.POST.get("misura", "count") or "count"}
    if lista:
        spec["lista"] = lista
    try:
        dati = interroga.calcola(spec, request)
    except ErroreInterrogazione as e:
        messages.error(request, f"Non si può salvare il grafico: {e}")
        return redirect(request.META.get("HTTP_REFERER") or reverse("core:dashboard"))
    titolo = request.POST.get("titolo", "").strip()[:200] or f"{vista.verbose_name_plural}: {motore.descrizione(spec, request)}"[:200]
    g = Grafico.objects.create(
        utente=request.user, pagina=_destinazione(request, request.POST.get("destinazione"), request.POST.get("titolo_nuova")),
        titolo=titolo, tipo=tipo if tipo in Grafico.INTERCAMBIABILI else Grafico.BARRE, spec=spec, dati=dati,
        origine=Grafico.VISTA, origine_url=(request.META.get("HTTP_REFERER") or "")[:300])
    from django.utils import timezone
    g.aggiornato = timezone.now()
    g.save(update_fields=["aggiornato"])
    messages.success(request, f"Grafico «{g.titolo}» salvato" + (f" nella pagina «{g.pagina.titolo}»." if g.pagina else " in libreria."))
    return _torna(request, g.pagina) if g.pagina else redirect("grafici:pagine")


def modulo_attivo():
    return "grafici" not in modules.disattivati()
