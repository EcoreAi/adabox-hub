"""Preventivi e ordini nel portale clienti: il cliente vede quelli della sua azienda, risponde ai preventivi inviati
(stessa pagina e stesse regole del link nell'email) e scarica il PDF."""
from urllib.parse import urlsplit

from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.formats import number_format

from portale.accesso import contesto, portale
from portale.stampa import risposta_pdf

from . import operazioni
from .models import OrdineVendita


def _ordini(accesso):
    return (OrdineVendita.objects.filter(azienda=accesso.azienda, cliente__in=accesso.contatti())
            .exclude(stato=OrdineVendita.BOZZA).order_by("-data", "-pk"))


def _link_risposta(ordine):
    """Il percorso della pagina per accettare o rifiutare, se il preventivo aspetta una risposta."""
    if ordine.stato != OrdineVendita.INVIATO or ordine.risposta:
        return ""
    return urlsplit(operazioni.link(ordine)).path            # solo il percorso: il cliente è già sul nostro sito


@portale
def ordini(request):
    elenco = [(o, _link_risposta(o)) for o in _ordini(request.accesso)[:200]]
    return render(request, "vendite/portale_ordini.html", contesto(request, ordini=elenco))


@portale
def pdf(request, pk):
    ordine = get_object_or_404(_ordini(request.accesso), pk=pk)
    return risposta_pdf(request, ordine, ordine.numero_ordine or ordine.numero or f"ordine-{ordine.pk}")


def riepilogo(accesso):
    da_rispondere = [o for o in _ordini(accesso).filter(stato=OrdineVendita.INVIATO, risposta="")[:4]]
    return {"conta": len(da_rispondere), "nota": "preventivi da guardare" if da_rispondere else "Nessun preventivo in attesa di risposta.",
            "voci": [(f"{o.numero} · {number_format(o.totale, 2, use_l10n=True, force_grouping=True)} €", _link_risposta(o) or reverse("vendite:portale_ordini"), "da rispondere") for o in da_rispondere]}
