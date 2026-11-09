"""Le pagine di Analisi: le schede della dashboard con i loro widget, i grafici salvati e le vie per salvarne di nuovi
(da un grafico dell'assistente, dalla vista Grafico di un modulo)."""
import json

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.http import Http404, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from core.registry import modules
from core.viste import interroga
from core.viste.interroga import ErroreInterrogazione

from . import motore
from .models import Grafico, Pagina

VISTA, MODIFICA, CONDIVIDI = "grafici.view_pagina", "grafici.change_pagina", "grafici.condividi_pagina"


# ---------- pagine ----------

def _mia(request, pk):
    return get_object_or_404(Pagina, pk=pk, utente=request.user, area__isnull=True)


def _visibile(request, pk):
    p = get_object_or_404(Pagina.objects.select_related("utente"), pk=pk, area__isnull=True)
    if p.utente_id != request.user.id and not motore.condivise(request.azienda, request.user).filter(pk=p.pk).exists():
        raise Http404
    return p


def _di_area(request, area):
    """La dashboard dell'area di lavoro, se l'utente vede l'area: la dispongono tutti i suoi membri."""
    p, info = motore.pagina_area(request.user, getattr(request, "azienda", None), area)
    if p is None:
        raise Http404
    return p, info


def _app(request, app):
    """La scheda dell'app per chi guarda: creata al primo accesso, così ha un layout e un titolo suoi."""
    p, info = motore.pagina_app(request.user, app)
    if p is None:
        raise Http404
    return p, info


def _torna(request, p):
    return redirect("grafici:pagina_app", app=p.app) if p.app else redirect("grafici:pagina", pk=p.pk)


def _rendi(request, p, info=None, area=None):
    visibili, nascosti = motore.catalogo(p, request)
    mio = p.utente_id == request.user.id or area is not None           # l'area la dispongono tutti i membri
    if area is not None:
        url_layout = reverse("grafici:layout_area", args=[area.pk])
    else:
        url_layout = reverse("grafici:layout_app", args=[p.app]) if p.app else reverse("grafici:layout", args=[p.pk])
    return render(request, "grafici/pagina.html", {
        "pagina": p, "info_app": info, "area": area, "widget": visibili, "nascosti": nascosti, "mio": mio,
        "personalizzata": bool(p.layout), "icone": motore.ICONE, "url_layout": url_layout,
        "contesto_ada": motore.contesto_ada(p, visibili), "scheda_attiva": p.chiave,
        "sorelle": [x for x in Pagina.objects.filter(utente=request.user, app="", area__isnull=True) if x.pk != p.pk]
        if mio and not p.app and area is None else [],
        "ai": motore._ai_disponibile(), "a_chi": motore.a_chi(p) if not p.app and area is None else "",
        "condivisione": _scelte_condivisione(p) if mio and not p.app and area is None
        and request.user.has_perm(CONDIVIDI) else None})


def _scelte_condivisione(p):
    from django.contrib.auth.models import Group

    from core.models import Ruolo
    scelti_r, scelti_g = set(p.ruoli.values_list("pk", flat=True)), set(p.gruppi.values_list("pk", flat=True))
    return {"ruoli": [(r, r.pk in scelti_r) for r in Ruolo.objects.order_by("ordine", "nome")],
            "gruppi": [(g, g.pk in scelti_g) for g in Group.objects.order_by("name")],
            "modo": "azienda" if p.condivisa else ("scelti" if scelti_r or scelti_g else "nessuno")}


@login_required
@permission_required(VISTA)
def pagina(request, pk):
    area = Pagina.objects.filter(pk=pk, area__isnull=False).values_list("area", flat=True).first()
    if area:
        return redirect("grafici:pagina_area", area=area)
    return _rendi(request, _visibile(request, pk))


@login_required
@permission_required(VISTA)
def pagina_app(request, app):
    p, info = _app(request, app)
    return _rendi(request, p, info)


@login_required
@permission_required(VISTA)
def pagina_area(request, area):
    p, a = _di_area(request, area)
    return _rendi(request, p, area=a)


@login_required
@permission_required(VISTA)
def pagine(request):
    """La scheda «Statistiche» della dashboard: i grafici delle app da esplorare, la libreria, le pagine dell'utente e
    quelle condivise con lui, le schede delle app nascoste."""
    mie = list(Pagina.objects.filter(utente=request.user, area__isnull=True))
    nascoste = {p.app for p in mie if p.app and p.nascosta}
    return render(request, "grafici/pagine.html", {
        "grafici_app": motore.grafici_delle_app(request.user),
        "libere": [p for p in mie if not p.app], "app_pagine": [p for p in mie if p.app],
        "condivise": motore.condivise(request.azienda, request.user).exclude(utente=request.user).select_related("utente"),
        "app_nascoste": [a for a in motore.app_con_indicatori(request.user) if a["slug"] in nascoste],
        "libreria": motore.libreria_di(request.user),
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
def layout_area(request, area):
    return _layout(request, _di_area(request, area)[0])


@login_required
@permission_required(MODIFICA)
@require_POST
def layout_app(request, app):
    return _layout(request, _app(request, app)[0])


@login_required
@permission_required("grafici.add_pagina")
@require_POST
def nuova(request):
    p = motore.nuova_pagina(request.user, request.POST.get("titolo", ""), request.POST.get("icona", "bar-chart"))
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
    p.delete()
    messages.success(request, "Pagina eliminata: i suoi grafici restano in libreria.")
    return redirect("core:dashboard")


@login_required
@permission_required(CONDIVIDI)
@require_POST
def condividi(request, pk):
    p = _mia(request, pk)
    if p.app:
        raise PermissionDenied("La scheda di un'app è personale.")
    from django.contrib.auth.models import Group

    from core.models import Ruolo
    modo = request.POST.get("a") or ("nessuno" if p.condivisa else "azienda")     # senza scelta: alterna come prima
    ids = lambda nome: [int(i) for i in request.POST.getlist(nome) if i.isdigit()]  # noqa: E731
    ruoli = Ruolo.objects.filter(pk__in=ids("ruoli")) if modo == "scelti" else Ruolo.objects.none()
    gruppi = Group.objects.filter(pk__in=ids("gruppi")) if modo == "scelti" else Group.objects.none()
    p.condivisa = modo == "azienda"
    p.save(update_fields=["condivisa", "aggiornata"])
    p.ruoli.set(ruoli)
    p.gruppi.set(gruppi)
    chi = motore.a_chi(p)
    messages.success(request, f"Pagina condivisa con {chi}: ognuno vede i dati che i suoi permessi gli consentono."
                     if chi else "La pagina è di nuovo solo tua.")
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
    area = Pagina.objects.filter(pk=pk, area__isnull=False).values_list("area", flat=True).first()
    p = _di_area(request, area)[0] if area else _visibile(request, pk)
    errori = 0
    for g in Grafico.objects.filter(utente=request.user, pk__in=[int(i[2:]) for i in p.id_widget if i.startswith("g:") and i[2:].isdigit()]):
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
    g = get_object_or_404(Grafico.objects.select_related("utente"), pk=pk)
    if not motore.puo_vedere(g, request.user, request.azienda):
        raise Http404
    return g


def _mio_grafico(request, pk):
    return get_object_or_404(Grafico, pk=pk, utente=request.user)


def _scelte_pagine(g, request):
    """Le pagine di chi guarda, con quelle in cui il grafico sta già; le schede delle app solo se già personali."""
    dentro = {p.pk for p in motore.pagine_con(g, request.user)}
    righe = [{"valore": motore.PANORAMICA, "titolo": "Dashboard", "dentro": motore.in_panoramica(g, request.user)}]
    righe += [{"valore": str(p.pk), "titolo": p.titolo, "dentro": p.pk in dentro} for p in Pagina.objects.filter(utente=request.user).order_by("app", "ordine", "pk")]
    return righe


def _persone(g, request):
    """Con chi si può condividere: i colleghi attivi, non i clienti del portale."""
    condivisi = set(g.condiviso_con.values_list("pk", flat=True))
    utenti = get_user_model().objects.none() if request.azienda is None else get_user_model().objects.filter(
        is_active=True, profilo__aziende=request.azienda).exclude(profilo__esterno=True).exclude(pk=g.utente_id).order_by("first_name", "last_name", "username")
    return [{"pk": u.pk, "nome": u.get_full_name() or u.get_username(), "dentro": u.pk in condivisi} for u in utenti]


@login_required
@permission_required("grafici.view_grafico")
@require_POST
def grafico_pagine(request, pk):
    """In quali delle mie pagine sta questo grafico: anche in più d'una, anche quello ricevuto da un collega."""
    g = _grafico_visibile(request, pk)
    scelte = set(request.POST.getlist("pagine"))
    for p in Pagina.objects.filter(utente=request.user):
        if str(p.pk) in scelte:
            motore.metti_in_pagina(p, g)
        elif g.id_widget in p.id_widget:
            motore.togli_da_pagina(p, g)
    motore.imposta_panoramica(g, request.user, motore.PANORAMICA in scelte)
    messages.success(request, "Pagine aggiornate.")
    return redirect("grafici:grafico", pk=pk)


@login_required
@permission_required("grafici.change_grafico")
@require_POST
def grafico_condividi(request, pk):
    """Con chi condividere un mio grafico. Chi lo riceve lo trova nella libreria e lo calcola con i propri permessi."""
    g = _mio_grafico(request, pk)
    ammessi = {r["pk"] for r in _persone(g, request)}
    scelti = {int(i) for i in request.POST.getlist("persone") if i.isdigit()} & ammessi
    nuovi = scelti - set(g.condiviso_con.values_list("pk", flat=True))
    g.condiviso_con.set(scelti)
    destinatari = [u.email for u in get_user_model().objects.filter(pk__in=nuovi) if u.email]
    if destinatari:
        link = f"{settings.SITO_URL}{reverse('grafici:grafico', args=[g.pk])}"
        send_mail(f"{request.user.get_full_name() or request.user.get_username()} ha condiviso un grafico con te", f"«{g.titolo}»\n{link}", None, destinatari, fail_silently=True)
    messages.success(request, f"Condiviso con {len(scelti)} person{'a' if len(scelti) == 1 else 'e'}." if scelti else "Il grafico non è più condiviso.")
    return redirect("grafici:grafico", pk=pk)


@login_required
@permission_required("grafici.view_grafico")
def grafico(request, pk):
    g = _grafico_visibile(request, pk)
    w = motore.widget_salvato(g, request, forza=bool(request.GET.get("aggiorna")))
    return render(request, "grafici/grafico.html", {
        "g": g, "w": w, "mio": w["mio"], "tipi": motore.TIPI_SCAMBIABILI, "scelte_pagine": _scelte_pagine(g, request), "persone": _persone(g, request),
        "contesto_ada": {"pagina": f"Grafico: {g.titolo}", "query": w["sotto"], "tipo": w["serie"]["tipo"], "dati": w["serie"]["righe"],
                         **({"previsione": w["serie"]["futuro"]} if w["serie"].get("futuro") else {})},
        "scheda_attiva": "", "ai": motore._ai_disponibile(), "aggiornamenti": motore.AGGIORNAMENTI})


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


def _metti(request, grafico, valore, titolo_nuova=""):
    """(titolo, indirizzo) del posto in cui il form ha messo il grafico; (None, None) se resta solo in libreria."""
    try:
        return motore.metti_in(request.user, valore, grafico, titolo_nuova, getattr(request, "azienda", None))
    except ValueError:
        raise Http404


@login_required
@permission_required("grafici.change_grafico")
@require_POST
def grafico_modifica(request, pk):
    g = _mio_grafico(request, pk)
    titolo = request.POST.get("titolo", "").strip()[:200]
    if titolo:
        g.titolo = titolo
    if request.POST.get("destinazione"):
        _metti(request, g, request.POST["destinazione"], request.POST.get("titolo_nuova"))
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
    id_widget = g.id_widget
    titolo = g.titolo
    g.delete()
    for p in Pagina.objects.filter(utente=request.user):
        if id_widget in p.id_widget:
            p.layout = motore._senza(p.layout, id_widget)
            p.save(update_fields=["layout", "aggiornata"])
    messages.success(request, f"Grafico «{titolo}» eliminato.")
    return redirect("grafici:pagine")


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
    a = get_object_or_404(Artifact, pk=request.POST.get("artifact"), utente=request.user, tipo__in=("grafico", "tabella"))
    if a.tipo == "tabella":
        tipo = Grafico.TABELLA
    else:
        tipo = a.spec.get("grafico", Grafico.BARRE)
        tipo = tipo if tipo in dict(Grafico.TIPI) and tipo != Grafico.TABELLA else Grafico.BARRE
    spec = {k: v for k, v in a.spec.items() if k not in ("tipo", "grafico")}
    g = Grafico.objects.create(
        utente=request.user,
        titolo=a.titolo, tipo=tipo, spec=spec, dati=a.dati,
        aggiornato=a.aggiornato or a.creato, origine=Grafico.CHAT,
        origine_url=reverse("ai:conversazione", args=[a.conversazione_id]) if a.conversazione_id else "")
    titolo, url = _metti(request, g, request.POST.get("destinazione"), request.POST.get("titolo_nuova"))
    return render(request, "grafici/_salvato.html", {"titolo": titolo, "url": url})


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
        utente=request.user,
        titolo=titolo, tipo=tipo if tipo in Grafico.INTERCAMBIABILI else Grafico.BARRE, spec=spec, dati=dati,
        origine=Grafico.VISTA, origine_url=(request.META.get("HTTP_REFERER") or "")[:300])
    from django.utils import timezone
    g.aggiornato = timezone.now()
    g.save(update_fields=["aggiornato"])
    dove, url = _metti(request, g, request.POST.get("destinazione"), request.POST.get("titolo_nuova"))
    messages.success(request, f"Grafico «{g.titolo}» salvato" + (f" in «{dove}»." if dove else " in libreria."))
    return redirect(url or "grafici:pagine")


def modulo_attivo():
    return "grafici" not in modules.disattivati()
