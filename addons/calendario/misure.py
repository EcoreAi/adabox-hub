"""Misura aziendale del Calendario (core.misure): gli appuntamenti, di default quelli dell'utente."""
from django.db.models import Q

from core.misure import Componente, Misura, registra


def _miei(request, di=""):
    """«Quanti appuntamenti ho» vuol dire i miei: organizzatore o partecipante. Con di="tutti", tutti quelli visibili."""
    if di == "tutti":
        return {}
    from .models import Evento
    utente = request.user
    ids = Evento.objects.filter(Q(organizzatore=utente) | Q(partecipanti=utente)).values_list("pk", flat=True).distinct()
    return {"id__in": list(ids)}


registra(Misura(
    nome="calendario.appuntamenti", etichetta="Appuntamenti", unita="",
    definizione="eventi del calendario in cui l'utente è organizzatore o partecipante (con di=tutti: tutti quelli che "
                "vede), per giorno di inizio",
    sinonimi=("appuntamenti", "riunioni", "agenda", "impegni"),
    raggruppamenti={"giorno": "inizio:giorno", "settimana": "inizio:settimana", "mese": "inizio:mese"},
    periodo_su="inizio", periodo_predefinito="oggi", filtri_dinamici=_miei,
    componenti=(Componente("calendario.eventi", "count"),)))
