"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
import datetime

from django.urls import reverse

from core.dashboard import queryset
from core.generici import url_record
from core.riepilogo import ATTENZIONE, dettagli_di, voce

from .models import Canone


def voci(request, dal, oggi):
    limite = oggi + datetime.timedelta(days=30)
    canoni = queryset(request, Canone).select_related("cliente")
    vicini = [c for c in canoni.filter(stato=Canone.ATTIVO, scadenza__isnull=False) if oggi <= c.limite_disdetta() <= limite]
    cessano = canoni.filter(stato=Canone.DISDETTO, cessa_il__lte=limite)
    return [
        voce(ATTENZIONE, len(vicini), "contratto ricorrente da confermare o disdire entro 30 giorni", "contratti ricorrenti da confermare o disdire entro 30 giorni",
             reverse("ricorrenti:cruscotto"), dettagli=[(f"{c} · {c.cliente} · disdetta entro il {c.limite_disdetta():%d/%m/%Y}", url_record(c) or "") for c in vicini[:5]]),
        voce(ATTENZIONE, cessano.count(), "contratto disdetto che cessa entro 30 giorni", "contratti disdetti che cessano entro 30 giorni", reverse("ricorrenti:cruscotto"),
             dettagli=dettagli_di(cessano, lambda c: f"{c} · {c.cliente} · fino al {c.cessa_il:%d/%m/%Y}")),
    ]
