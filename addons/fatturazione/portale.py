"""Fatture nel portale clienti: il cliente vede le fatture emesse alla sua azienda, quanto resta da pagare e la
prossima scadenza, e scarica il PDF."""
from decimal import Decimal

from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from portale.accesso import contesto, portale
from portale.stampa import risposta_pdf

from .models import Fattura


def euro(importo):
    from django.utils.formats import number_format
    return number_format(importo, 2, use_l10n=True, force_grouping=True)


def _fatture(accesso):
    return (Fattura.objects.filter(azienda=accesso.azienda, cliente__in=accesso.contatti(), stato=Fattura.EMESSA)
            .prefetch_related("scadenze").order_by("-data", "-pk"))


def _prossima(fattura):
    aperte = [s for s in fattura.scadenze.all() if s.residuo > 0]
    return min((s.data for s in aperte), default=None)


def _pagabile_online():
    """Con il modulo Pagamenti online: la funzione che dice se una fattura si paga con «Paga ora»."""
    from django.apps import apps
    if not apps.is_installed("pagamenti"):
        return lambda fattura: False
    from pagamenti.servizi import pagabile
    return pagabile


@portale
def fatture(request):
    pagabile = _pagabile_online()
    elenco = [(f, f.residuo, _prossima(f), pagabile(f)) for f in _fatture(request.accesso)[:200]]
    return render(request, "fatturazione/portale_fatture.html", contesto(request, fatture=elenco))


@portale
def pdf(request, pk):
    fattura = get_object_or_404(_fatture(request.accesso), pk=pk)
    return risposta_pdf(request, fattura, f"fattura-{fattura.numero or fattura.pk}".replace("/", "-"))


def riepilogo(accesso):
    da_pagare = [f for f in _fatture(accesso) if not f.pagata and f.residuo > 0]
    totale = sum((f.residuo for f in da_pagare), Decimal(0))
    return {"conta": len(da_pagare), "nota": f"da pagare, in tutto {euro(totale)} €" if da_pagare else "Nessuna fattura da pagare.",
            "voci": [(f"{f.numero} · {euro(f.residuo)} €", reverse("fatturazione:portale_fatture"), "scade " + d.strftime("%d/%m/%Y") if (d := _prossima(f)) else "")
                     for f in da_pagare[:4]]}
