"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
import datetime

from django.urls import reverse
from django.utils.formats import date_format

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, voce

from .models import RigaOre


def voci(request, dal, oggi):
    """Chi registra le ore di solito e ieri non l'ha fatto: un promemoria, non un rimprovero."""
    mie = queryset(request, RigaOre).filter(utente=request.user)
    ieri = oggi - datetime.timedelta(days=1)
    while ieri.weekday() >= 5:
        ieri -= datetime.timedelta(days=1)
    abituale = mie.filter(data__gte=oggi - datetime.timedelta(days=30), data__lt=ieri).exists()
    if not abituale or mie.filter(data=ieri).exists():
        return []
    return [voce(ATTENZIONE, 1, "", url=reverse("timesheet:settimana"), testo=f"{date_format(ieri, 'l j F').capitalize()}: non hai registrato ore")]
