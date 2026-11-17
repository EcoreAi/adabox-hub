"""I grafici salvati e le pagine di Analisi nella ricerca generale («Cerca ovunque», core.cerca): solo quelli che chi
cerca vede (i suoi, quelli condivisi con lui, le pagine condivise con la sua azienda, il suo ruolo o un suo gruppo)."""
from django.urls import reverse

from . import motore
from .models import Pagina


def voci(request):
    utente = request.user
    grafici = [{"titolo": g.titolo, "url": reverse("grafici:grafico", args=[g.pk]), "sotto": "Grafico salvato"}
               for g in motore.libreria_di(utente)]
    pagine = (Pagina.objects.filter(utente=utente) | motore.condivise(getattr(request, "azienda", None), utente)).distinct()
    return {"gruppo": "Grafici e pagine di Analisi", "grafici": True,
            "voci": grafici + [{"titolo": p.titolo, "url": motore.url_pagina(p), "sotto": "Pagina di Analisi"} for p in pagine]}
