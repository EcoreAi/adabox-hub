import datetime

from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, voce

from .models import RataFinanziamento


def voci(request, dal, oggi):
    if not request.user.has_perm("finanziamenti.view_ratafinanziamento"):
        return [voce(ATTENZIONE, 0, "rata da pagare", "rate da pagare")]
    rate = (queryset(request, RataFinanziamento).filter(pagata=False, data__lte=oggi + datetime.timedelta(days=7))
            .select_related("finanziamento").order_by("data"))
    righe = [(f"{r.finanziamento} · {r.importo:.2f} € il {r.data:%d/%m}" + (" (scaduta)" if r.data < oggi else ""),
              reverse("finanziamenti:rate_dettaglio", args=[r.pk])) for r in rate[:5]]
    return [voce(ATTENZIONE, rate.count(), "rata da pagare entro 7 giorni", "rate da pagare entro 7 giorni",
                 reverse("finanziamenti:rate_lista") + "?pagata=0", dettagli=righe)]
