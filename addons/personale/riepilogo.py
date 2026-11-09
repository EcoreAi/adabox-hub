"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, OGGI, dettagli_di, voce

from .models import Assenza


def voci(request, dal, oggi):
    assenze = queryset(request, Assenza).select_related("dipendente", "tipo")
    da_approvare = assenze.filter(stato=Assenza.RICHIESTA).exclude(dipendente__utente=request.user)
    assenti = assenze.filter(stato=Assenza.APPROVATA, dal__lte=oggi, al__gte=oggi).exclude(dipendente__utente=request.user)
    mie = assenze.filter(dipendente__utente=request.user, decisa_il__gte=dal, stato__in=(Assenza.APPROVATA, Assenza.RIFIUTATA))
    return [
        voce(ATTENZIONE, da_approvare.count(), "richiesta di assenza da approvare", "richieste di assenza da approvare", reverse("personale:assenze_lista"),
             dettagli=dettagli_di(da_approvare, lambda a: f"{a.dipendente} · {a.tipo} dal {a.dal:%d/%m} al {a.al:%d/%m}")),
        voce(OGGI, assenti.count(), "collega assente oggi", "colleghi assenti oggi", reverse("personale:assenze_calendario"), dettagli=dettagli_di(assenti, lambda a: f"{a.dipendente} · {a.tipo}")),
        voce(NOVITA, mie.count(), "tua richiesta di assenza decisa", "tue richieste di assenza decise", reverse("personale:mie"),
             dettagli=dettagli_di(mie, lambda a: f"{a.get_stato_display()} · {a.tipo} dal {a.dal:%d/%m}")),
        _contratti(request, oggi),
    ]


def _contratti(request, oggi):
    """I contratti in scadenza nei prossimi 30 giorni, a chi vede i contratti."""
    from . import contratti
    from .models import ContrattoLavoro
    if not request.user.has_perm("personale.view_contrattolavoro"):
        return voce(ATTENZIONE, 0, "contratto in scadenza", "contratti in scadenza")
    scadono = contratti.in_scadenza(queryset(request, ContrattoLavoro), oggi)
    return voce(ATTENZIONE, len(scadono), "contratto in scadenza", "contratti in scadenza", reverse("personale:contratti_lista"),
                dettagli=[(f"{c.dipendente} · {c.get_tipo_display()} fino al {c.al:%d/%m/%Y}", reverse("personale:contratti_dettaglio", args=[c.pk]))
                          for c in scadono[:5]])
