"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset
from core.generici import url_record
from core.riepilogo import OGGI, voce

from .models import Evento


def voci(request, dal, oggi):
    eventi = queryset(request, Evento).filter(inizio__date=oggi).order_by("inizio")
    miei = eventi.filter(Q(organizzatore=request.user) | Q(partecipanti=request.user)).distinct()
    scelti = miei if miei.exists() else eventi
    righe = [(f"{'tutto il giorno' if e.tutto_il_giorno else timezone.localtime(e.inizio).strftime('%H:%M')} · {e.titolo}", url_record(e) or "") for e in scelti[:5]]
    return [voce(OGGI, scelti.count(), "appuntamento oggi", "appuntamenti oggi", reverse("calendario:eventi_calendario"), dettagli=righe)]
