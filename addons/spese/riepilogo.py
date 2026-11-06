"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, dettagli_di, voce
from core.viste.gruppi import numero

from .models import NotaSpese


def voci(request, dal, oggi):
    note = queryset(request, NotaSpese).select_related("dipendente")
    lista = reverse("spese:note_lista")
    da_approvare = note.filter(stato=NotaSpese.INVIATA).exclude(dipendente__utente=request.user)
    rimborsate = note.filter(dipendente__utente=request.user, stato=NotaSpese.RIMBORSATA, rimborsata_il__gte=timezone.localtime(dal).date())
    return [
        voce(ATTENZIONE, da_approvare.count(), "nota spese da approvare", "note spese da approvare", lista + "?f_stato=inviata",
             dettagli=dettagli_di(da_approvare, lambda n: f"{n.titolo} · {n.dipendente} · {numero(n.totale)} €")),
        voce(NOVITA, rimborsate.count(), "tua nota spese rimborsata", "tue note spese rimborsate", lista, dettagli=dettagli_di(rimborsate, lambda n: f"{n.titolo} · {numero(n.totale)} €")),
    ]
