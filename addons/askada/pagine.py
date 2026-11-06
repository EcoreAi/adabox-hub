"""La finestra «Chiedi ad Ada»: la domanda parte con allegato ciò che la pagina mostra, e la risposta arriva in diretta dal modulo AI."""
import json

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ai import motore
from ai.models import Conversazione
from ai.pagine import app_selezionabili
from core import parametri

from .models import Domanda

PERMESSO = "askada.add_domanda"
MAX_JSON = 8000


def _app(url, user):
    """L'app della pagina, se è una di quelle a cui l'assistente può limitarsi."""
    slug = url.lstrip("/").split("/", 1)[0]
    return slug if slug in {a["slug"] for a in app_selezionabili(user)} else ""


def suggerimenti(request):
    voci = ["Spiegami questa pagina"]
    if request.GET.get("grafici"):
        voci.append("Spiegami i grafici")
    if request.GET.get("kpi"):
        voci.append("Spiegami i KPI")
    if request.GET.get("grafico"):
        voci.append("Spiegami questo grafico")
    if request.GET.get("analisi"):
        voci += ["Cosa è cambiato rispetto al periodo prima?", "Quale grafico merita attenzione?"]
    voci.append("Che cosa dovrei fare qui?")
    return voci


def _nota(url, titolo, contesto, pagina):
    righe = [f"L'utente ha premuto «Chiedi ad Ada» sulla pagina «{titolo}» ({url}) e chiede di quella pagina: rispondi in base a "
             "ciò che la pagina mostra, chiaro e breve; se la domanda riguarda altro, dillo."]
    if contesto:
        righe.append("Dati strutturati della pagina (JSON):\n" + contesto)
    if pagina:
        righe.append("Testo visibile della pagina:\n" + pagina)
    return "\n".join(righe)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def apri(request):
    url, titolo = request.GET.get("url", "")[:300], request.GET.get("titolo", "")[:200]
    recenti = Domanda.objects.filter(utente=request.user, url=url, conversazione__isnull=False).select_related("conversazione")[:3]
    return render(request, "askada/_modale.html", {"url": url, "titolo": titolo or "questa pagina", "suggerimenti": suggerimenti(request), "recenti": recenti})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def chiedi(request):
    if not request.user.has_perm("ai.add_conversazione"):
        raise PermissionDenied
    testo = request.POST.get("testo", "").strip()[:4000]
    if not testo:
        return HttpResponseBadRequest("Scrivi una domanda.")
    url, titolo = request.POST.get("url", "")[:300], request.POST.get("titolo", "")[:200]
    contesto = request.POST.get("contesto", "")[:MAX_JSON]
    try:
        json.loads(contesto) if contesto else None
    except ValueError:
        contesto = ""
    pagina = request.POST.get("pagina", "")[:int(parametri.leggi("askada.caratteri_max") or 6000)]
    pk = request.POST.get("conversazione", "")
    conversazione = Conversazione.objects.filter(pk=pk, utente=request.user).first() if pk.isdigit() else None
    if conversazione is None:
        nome = f"{titolo or 'Chiedi ad Ada'} · {' '.join(testo.split())}"
        conversazione = Conversazione.objects.create(utente=request.user, ambito=_app(url, request.user), titolo_generato=True,
                                                     titolo=nome[:117] + ("…" if len(nome) > 117 else ""))
    primo = conversazione.messaggi.order_by("-pk").values_list("pk", flat=True).first() or 0
    turno = motore.avvia(conversazione, testo, request.user, getattr(request, "azienda", None), nota=_nota(url, titolo, contesto, pagina))
    conversazione.save(update_fields=["aggiornata"])
    Domanda.objects.create(utente=request.user, url=url, titolo=titolo, testo=testo, conversazione=conversazione)
    turno.refresh_from_db()
    return render(request, "askada/_risposta.html", {"messaggi": conversazione.messaggi.filter(pk__gt=primo),
                                                      "turno": None if turno.concluso else turno, "conversazione": conversazione})
