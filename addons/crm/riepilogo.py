"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, OGGI, dettagli_di, voce
from core.viste.gruppi import numero

from .models import Opportunita


def _riga(o):
    return f"{o} · {numero(o.valore_atteso)} €"


def voci(request, dal, oggi):
    opp = queryset(request, Opportunita)
    lista = reverse("crm:opportunita_lista")
    giorno = timezone.localtime(dal).date()
    vinte, perse = opp.filter(stato=Opportunita.VINTA, chiusa_il__gte=giorno), opp.filter(stato=Opportunita.PERSA, chiusa_il__gte=giorno)
    aperte = opp.filter(stato=Opportunita.APERTA)
    di_oggi, scadute = aperte.filter(chiusura_prevista=oggi), aperte.filter(chiusura_prevista__lt=oggi)
    valore = vinte.aggregate(t=Sum("valore_atteso"))["t"] or 0
    return [
        voce(NOVITA, vinte.count(), "opportunità vinta", "opportunità vinte", lista + "?f_stato=vinta", dettagli=dettagli_di(vinte, _riga), nota=f"{numero(valore)} €"),
        voce(NOVITA, perse.count(), "opportunità persa", "opportunità perse", lista + "?f_stato=persa", dettagli=dettagli_di(perse, _riga)),
        voce(OGGI, di_oggi.count(), "opportunità con chiusura prevista oggi", "opportunità con chiusura prevista oggi", lista, dettagli=dettagli_di(di_oggi, _riga)),
        voce(ATTENZIONE, scadute.count(), "opportunità oltre la chiusura prevista", "opportunità oltre la chiusura prevista", lista + "?f_stato=aperta", urgente=True, dettagli=dettagli_di(scadute, _riga)),
    ]
