"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.dashboard import queryset
from core.generici import url_record
from core.riepilogo import ATTENZIONE, voce
from progetti.models import Progetto


def voci(request, dal, oggi):
    from . import pagine, piano
    azienda = getattr(request, "azienda", None)
    progetti = list(queryset(request, Progetto).filter(stato=Progetto.ATTIVO))
    if azienda is None or not progetti:
        return []
    calcolato = piano.calcola(azienda, oggi)
    tardi = [s for s in (pagine.scheda_progetto(calcolato, p) for p in progetti) if s["ritardo"]]
    return [voce(ATTENZIONE, len(tardi), "progetto in ritardo sulla consegna promessa", "progetti in ritardo sulla consegna promessa", reverse("capacita:consegne"), urgente=True,
                 dettagli=[(f"{s['progetto']} · +{s['ritardo']} giorni", url_record(s["progetto"]) or "") for s in tardi[:5]])]
