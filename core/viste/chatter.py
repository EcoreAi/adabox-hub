"""Pannello del chatter nel dettaglio: messaggi, note, allegati, follower (viste HTMX con fallback)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from core import allegati, chatter
from core.generici import ct_di, vista_e_oggetto
from core.models import Messaggio

PER_PAGINA = 20


def contesto_chatter(request, vista, obj, pagina=1):
    pagina_messaggi = Paginator(chatter.messaggi_di(obj), PER_PAGINA).get_page(pagina)
    return {
        "ct": ct_di(obj).pk, "obj": obj, "messaggi": pagina_messaggi,
        "follower": chatter.follower_di(obj), "segue": chatter.segue(obj, request.user),
        "allegati": allegati.di(obj), "puo_modificare": vista.has_change_permission(request, obj),
    }


def _pannello(request, vista, obj):
    return render(request, "core/chatter/_pannello.html", {"chatter": contesto_chatter(request, vista, obj)})


def _risposta(request, vista, obj):
    if request.headers.get("HX-Request"):
        return _pannello(request, vista, obj)
    return redirect(vista.url("dettaglio", pk=obj.pk))


@require_GET
@login_required
def pannello(request, ct, pk):
    vista, obj = vista_e_oggetto(request, ct, pk, "view")
    return _pannello(request, vista, obj)


@require_GET
@login_required
def altri_messaggi(request, ct, pk):
    vista, obj = vista_e_oggetto(request, ct, pk, "view")
    return render(request, "core/chatter/_messaggi.html",
                  {"chatter": contesto_chatter(request, vista, obj, request.GET.get("p", 1))})


@require_POST
@login_required
def scrivi(request, ct, pk):
    """Nota interna o messaggio ai follower, con allegati. Basta poter vedere il record."""
    vista, obj = vista_e_oggetto(request, ct, pk, "view")
    corpo = request.POST.get("corpo", "").strip()
    tipo = Messaggio.NOTA if request.POST.get("tipo") == "nota" else Messaggio.MESSAGGIO
    file = []
    for f in request.FILES.getlist("file"):
        try:
            file.append(allegati.salva(obj, f, request.user))
        except allegati.AllegatoNonValido as e:
            messages.error(request, str(e))
    if corpo or file:
        chatter.scrivi(obj, request.user, corpo, tipo, allegati=file)
    else:
        messages.warning(request, "Scrivi un testo o allega un file.")
    return _risposta(request, vista, obj)


@require_POST
@login_required
def segui(request, ct, pk):
    vista, obj = vista_e_oggetto(request, ct, pk, "view")
    if request.POST.get("azione") == "smetti":
        chatter.smetti(obj, request.user)
    else:
        chatter.segui(obj, request.user)
    return _risposta(request, vista, obj)
