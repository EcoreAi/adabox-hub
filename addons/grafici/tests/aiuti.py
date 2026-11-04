"""Un grafico salvato già messo in una pagina."""
from grafici import motore
from grafici.models import Grafico


def in_pagina(pagina, **campi):
    g = Grafico.objects.create(**campi)
    motore.metti_in_pagina(pagina, g)
    pagina.refresh_from_db()
    return g
