"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, dettagli_di, voce
from core.viste.gruppi import numero

from .models import CollegamentoConto, MovimentoBanca


def voci(request, dal, oggi):
    aperti = queryset(request, MovimentoBanca).filter(stato__in=(MovimentoBanca.DA_ABBINARE, MovimentoBanca.PARZIALE))
    return [voce(ATTENZIONE, aperti.count(), "movimento bancario da abbinare", "movimenti bancari da abbinare", reverse("banca:riconcilia"),
                 dettagli=dettagli_di(aperti, lambda m: f"{m.data:%d/%m} · {numero(m.importo)} € · {m.controparte or m.descrizione[:40]}")),
            _consensi(request)]


def _consensi(request):
    """I conti collegati il cui consenso scade fra poco (o è scaduto): senza rinnovo i movimenti smettono di arrivare."""
    from . import sincronia
    if not request.user.has_perm("banca.add_collegamentoconto") or getattr(request, "azienda", None) is None:
        return voce(ATTENZIONE, 0, "consenso della banca da rinnovare", "consensi della banca da rinnovare")
    da_rinnovare = sincronia.in_scadenza(request.azienda)
    primo = da_rinnovare.first()
    return voce(ATTENZIONE, da_rinnovare.count(), "consenso della banca da rinnovare", "consensi della banca da rinnovare",
                reverse("banca:conti_dettaglio", args=[primo.conto_id]) if primo else "",
                dettagli=dettagli_di(da_rinnovare, lambda c: f"{c.conto} · scade il {c.scade_il:%d/%m}"))
