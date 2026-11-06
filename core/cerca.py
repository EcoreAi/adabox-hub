"""La ricerca in tutte le app: i campi di ricerca di ogni vista che l'utente può vedere, con i suoi permessi e la sua
azienda. Una query per vista: per questo si cerca all'invio, con un tetto di tempo, e pochi risultati per vista."""
import time

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import NoReverseMatch

from .viste import filtri
from .viste.interroga import viste_accessibili

PER_VISTA = 5
TEMPO_MASSIMO = 3.0
LUNGHEZZA_MINIMA = 2


def cerca(request, testo):
    """([{"vista", "app", "totale", "url", "voci": [{"titolo", "url"}]}], completa)."""
    gruppi, inizio = [], time.monotonic()
    for vista in viste_accessibili(request):
        if not vista.search_fields:
            continue
        if time.monotonic() - inizio > TEMPO_MASSIMO:
            return gruppi, False
        qs = filtri.applica(vista, request, vista.get_queryset(request), parametri={"q": testo})
        voci = list(qs[:PER_VISTA + 1])
        if not voci:
            continue
        try:
            righe = [{"titolo": str(o), "url": vista.url("dettaglio", pk=o.pk)} for o in voci[:PER_VISTA]]
            url = f"{vista.url('lista')}?q="
        except NoReverseMatch:
            continue
        gruppi.append({"vista": str(vista.verbose_name_plural).capitalize(), "app": vista.modulo, "url": url, "voci": righe, "altri": len(voci) > PER_VISTA})
    return gruppi, True


@login_required
def pagina(request):
    testo = request.GET.get("q", "").strip()[:100]
    gruppi, completa = (cerca(request, testo) if len(testo) >= LUNGHEZZA_MINIMA else ([], True))
    return render(request, "core/cerca.html", {"q": testo, "gruppi": gruppi, "completa": completa, "troppo_corta": 0 < len(testo) < LUNGHEZZA_MINIMA})
