"""KPI del Personale per la dashboard."""
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset

from . import flusso, saldi
from .models import Assenza, Dipendente


def kpi(request):
    oggi = timezone.localdate()
    assenze = queryset(request, Assenza)
    u = request.user
    da_approvare = assenze.filter(stato=Assenza.RICHIESTA)
    if not flusso.gestore(u):
        da_approvare = da_approvare.filter(Q(dipendente__responsabile__utente=u)
                                           | Q(dipendente__reparto__responsabile__utente=u))
    voci = [{"valore": assenze.filter(stato=Assenza.APPROVATA, dal__lte=oggi, al__gte=oggi).count(),
             "etichetta": "assenti oggi", "url": reverse("personale:assenze_calendario")},
            {"valore": da_approvare.count(), "etichetta": "richieste da approvare",
             "url": reverse("personale:assenze_lista") + "?f_stato=richiesta"}]
    mio = Dipendente.objects.filter(utente=u, attivo=True).first()
    if mio is not None:
        voci.append({"valore": f"{saldi.saldo(mio, oggi.year)['ferie']['residue'].normalize():f}", "etichetta": "tue ferie residue",
                     "url": reverse("personale:mie")})
    return {"kpi": voci}
