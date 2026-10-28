"""KPI dei Documenti per la dashboard."""
import datetime

from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils import timezone

from . import accesso, servizi


def kpi(request):
    azienda = getattr(request, "azienda", None)
    if azienda is None or not request.user.has_perm("documenti.view_documento"):
        return {"kpi": []}
    documenti = accesso.documenti(request.user, azienda).filter(cestinato_il__isnull=True)
    settimana = timezone.now() - datetime.timedelta(days=7)
    return {"kpi": [
        {"valore": documenti.count(), "etichetta": "documenti", "url": reverse("documenti:archivio")},
        {"valore": documenti.filter(creato__gte=settimana).count(), "etichetta": "caricati negli ultimi 7 giorni"},
        {"valore": filesizeformat(servizi.spazio_usato(azienda)), "etichetta": "spazio usato"},
    ]}
