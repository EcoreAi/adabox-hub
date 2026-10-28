"""KPI delle Note spese per la dashboard."""
from django.db.models import Q, Sum
from django.urls import reverse

from core.dashboard import queryset
from core.viste.gruppi import numero

from . import flusso
from .models import NotaSpese


def kpi(request):
    note = queryset(request, NotaSpese)
    u = request.user
    da_approvare = note.filter(stato=NotaSpese.INVIATA).exclude(dipendente__utente=u)
    if not flusso.gestore(u):
        da_approvare = da_approvare.filter(Q(dipendente__responsabile__utente=u)
                                           | Q(dipendente__reparto__responsabile__utente=u))
    lista = reverse("spese:note_lista")
    return {"kpi": [
        {"valore": da_approvare.count(), "etichetta": "note spese da approvare", "url": f"{lista}?f_stato=inviata"},
        {"valore": f"{numero(note.filter(stato=NotaSpese.APPROVATA).aggregate(t=Sum('totale'))['t'] or 0)} €",
         "etichetta": "da rimborsare", "url": f"{lista}?f_stato=approvata"},
        {"valore": note.filter(dipendente__utente=u, stato=NotaSpese.BOZZA).count(), "etichetta": "tue note in bozza"},
    ]}
