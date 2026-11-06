"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, dettagli_di, voce
from core.viste.gruppi import numero

from .models import MovimentoBanca


def voci(request, dal, oggi):
    aperti = queryset(request, MovimentoBanca).filter(stato__in=(MovimentoBanca.DA_ABBINARE, MovimentoBanca.PARZIALE))
    return [voce(ATTENZIONE, aperti.count(), "movimento bancario da abbinare", "movimenti bancari da abbinare", reverse("banca:riconcilia"),
                 dettagli=dettagli_di(aperti, lambda m: f"{m.data:%d/%m} · {numero(m.importo)} € · {m.controparte or m.descrizione[:40]}"))]
