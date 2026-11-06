"""La scheda del riepilogo: come finestra sopra la pagina (htmx) o come pagina intera."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import accessi, motore

PERMESSO = "riepilogo.view_preferenza"


def _contesto(request):
    p = accessi.di(request.user)
    scelta = request.GET.get("da", "accesso")
    if scelta not in dict(motore.SCELTE):
        scelta = "accesso"
    dal, testo = motore.da_quando(p, scelta)
    dati = motore.calcola(request, dal, silenziate=p.silenziate)
    p.aperto_il = timezone.now()
    p.save(update_fields=["aperto_il"])
    return {"preferenza": p, "scelta": scelta, "scelte": motore.SCELTE, "dal_testo": testo, "saluto": motore.saluto(request.user),
            "silenziate": len(p.silenziate), **dati}


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pannello(request):
    if request.GET.get("apertura") == "login":
        request.session.pop(accessi.CHIAVE_SESSIONE, None)
    return render(request, "riepilogo/_pannello.html", {**_contesto(request), "in_pannello": True})


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pagina(request):
    request.session.pop(accessi.CHIAVE_SESSIONE, None)
    return render(request, "riepilogo/pagina.html", _contesto(request))


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def preferenza(request):
    """Solo la propria: «apri da solo quando accedo»."""
    p = accessi.di(request.user)
    p.mostra_al_login = request.POST.get("mostra") == "1"
    p.save(update_fields=["mostra_al_login"])
    return HttpResponse(status=204)


def _catalogo(request, p):
    """Tutte le voci che l'utente potrebbe vedere, raggruppate per modulo, anche quelle a zero."""
    dal, _ = motore.da_quando(p, "settimana")
    voci = motore.calcola(request, dal, tutte=True)["voci"]
    moduli, sezioni = [], dict((c, t) for c, t, _ in motore.contratto.SEZIONI)
    for v in voci:
        if not moduli or moduli[-1]["nome"] != v["modulo"]:
            moduli.append({"nome": v["modulo"], "voci": []})
        moduli[-1]["voci"].append({**v, "sezione_testo": sezioni[v["sezione"]]})
    return moduli


@login_required
@permission_required(PERMESSO, raise_exception=True)
def impostazioni(request):
    """Che cosa mostrare: ogni voce si può spegnere; e se la scheda deve aprirsi da sola."""
    p = accessi.di(request.user)
    moduli = _catalogo(request, p)
    if request.method == "POST":
        mostrate = set(request.POST.getlist("mostra"))
        p.silenziate = [v["chiave"] for m in moduli for v in m["voci"] if v["chiave"] not in mostrate]
        p.mostra_al_login = request.POST.get("mostra_al_login") == "1"
        p.save(update_fields=["silenziate", "mostra_al_login"])
        messages.success(request, f"Salvato: {len(p.silenziate)} voc{'e' if len(p.silenziate) == 1 else 'i'} silenziat{'a' if len(p.silenziate) == 1 else 'e'}.")
        return redirect("riepilogo:impostazioni")
    return render(request, "riepilogo/impostazioni.html", {"preferenza": p, "moduli": moduli, "silenziate": len(p.silenziate)})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def silenzia(request):
    """Il bottone sulla voce: la spegne, o la riaccende se era spenta. Dal pannello torna il pannello aggiornato."""
    p = accessi.di(request.user)
    chiave = request.POST.get("chiave", "")[:120]
    if not chiave:
        return HttpResponse(status=400)
    if chiave in p.silenziate:
        p.silenziate = [c for c in p.silenziate if c != chiave]
    else:
        p.silenziate = [*p.silenziate, chiave]
    p.save(update_fields=["silenziate"])
    if request.headers.get("HX-Request"):
        return render(request, "riepilogo/_pannello.html", {**_contesto(request), "in_pannello": True})
    return redirect(request.POST.get("ritorno") or "riepilogo:pagina")
