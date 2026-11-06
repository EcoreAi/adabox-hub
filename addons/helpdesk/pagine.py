"""Pagine pubbliche dell'helpdesk: la valutazione dal link nell'email e la guida online."""
from django.core import signing
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core import attivita, chatter
from core.models import Messaggio, TipoAttivita

from . import guida as motore
from .lavori import SALE_VALUTAZIONE
from .models import Articolo, CategoriaArticolo, Ticket, Valutazione

GIORNI_VALIDITA = 90


def _segnala_voto_basso(ticket, valutazione):
    """Voto basso: una nota interna e un'attività a chi ha seguito il ticket, per richiamare il cliente."""
    chatter.scrivi(ticket, None, f"Valutazione del cliente: {valutazione.stelle}\n{valutazione.commento}".strip(), tipo=Messaggio.NOTA)
    tipo = TipoAttivita.objects.order_by("ordine", "pk").first()
    chi = ticket.assegnatario or (ticket.team.membri.first() if ticket.team_id else None)
    if tipo and chi:
        attivita.pianifica(ticket, tipo, chi, riepilogo=f"Richiama il cliente: valutazione {valutazione.voto}/5")


def valuta(request, token):
    try:
        pk = signing.loads(token, salt=SALE_VALUTAZIONE, max_age=GIORNI_VALIDITA * 86400)
    except signing.BadSignature:
        return render(request, "helpdesk/valuta.html", {"scaduto": True}, status=400)
    ticket = get_object_or_404(Ticket, pk=pk)
    esistente = Valutazione.objects.filter(ticket=ticket).first()
    if request.method == "POST":
        voto = request.POST.get("voto", "")
        if voto not in {"1", "2", "3", "4", "5"}:
            return render(request, "helpdesk/valuta.html", {"ticket": ticket, "esistente": esistente, "errore": True, "voti": range(1, 6)})
        nuova = esistente is None
        esistente, _ = Valutazione.objects.update_or_create(ticket=ticket, defaults={
            "voto": int(voto), "commento": request.POST.get("commento", "")[:4000]})
        if nuova and esistente.voto <= 2:
            _segnala_voto_basso(ticket, esistente)
        return render(request, "helpdesk/valuta.html", {"ticket": ticket, "esistente": esistente, "grazie": True})
    return render(request, "helpdesk/valuta.html", {"ticket": ticket, "esistente": esistente, "voti": range(1, 6)})


def _visibili():
    return Articolo.objects.filter(pubblicato=True, pubblico=True)


def guida(request):
    testo = request.GET.get("q", "").strip()
    return render(request, "helpdesk/guida.html", contesto_guida(_visibili(), testo))


def contesto_guida(articoli, testo):
    if testo:
        return {"q": testo, "risultati": motore.cerca(articoli, testo, 30)}
    categorie = (CategoriaArticolo.objects.filter(articoli__in=articoli).distinct()
                 .prefetch_related("articoli"))
    per_categoria = [{"categoria": c, "articoli": [a for a in c.articoli.all() if a in articoli]} for c in categorie]
    return {"q": "", "categorie": per_categoria, "senza": articoli.filter(categoria=None),
            "popolari": articoli.order_by("-visite")[:5]}


def articolo(request, pk):
    voce = get_object_or_404(_visibili(), pk=pk)
    Articolo.objects.filter(pk=pk).update(visite=F("visite") + 1)
    return render(request, "helpdesk/articolo.html", {"articolo": voce, "utile_url": reverse("helpdesk:guida_utile", args=[pk]),
                                                      "indietro": reverse("helpdesk:guida"), "voto_dato": _voto_dato(request, pk)})


def _voto_dato(request, pk):
    return pk in request.session.get("guida_voti", [])


def registra_utilita(request, articoli, pk):
    """Un voto per sessione: si conta quanto serve l'articolo, non chi l'ha letto."""
    voce = get_object_or_404(articoli, pk=pk)
    if not _voto_dato(request, pk):
        campo = "utile_si" if request.POST.get("utile") == "si" else "utile_no"
        Articolo.objects.filter(pk=voce.pk).update(**{campo: F(campo) + 1})
        request.session["guida_voti"] = [*request.session.get("guida_voti", []), pk]
    return voce


@require_POST
def guida_utile(request, pk):
    registra_utilita(request, _visibili(), pk)
    return redirect("helpdesk:guida_articolo", pk=pk)


def guida_cerca(request):
    return JsonResponse({"articoli": [{"titolo": a.titolo, "url": reverse("helpdesk:guida_articolo", args=[a.pk])}
                                      for a in motore.cerca(_visibili(), request.GET.get("q", ""))]})

