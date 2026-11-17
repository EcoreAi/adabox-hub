"""KPI e grafici della Fatturazione per la dashboard."""
import datetime

from django.urls import reverse
from django.utils import timezone

from core import misure
from core.dashboard import numero, queryset
from core.viste.interroga import ErroreInterrogazione

from .models import Fattura

MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
NON_DISPONIBILE = "non disponibile"


def _euro(nome, request, **parametri):
    """Il valore di una misura aziendale (core.misure) in euro, o «non disponibile» se il ruolo non vede i suoi campi."""
    try:
        return f"{numero(misure.calcola(nome, request, **parametri)['valore'])} €"
    except ErroreInterrogazione:
        return NON_DISPONIBILE


def _ultimi_mesi(request, mesi, oggi):
    try:
        gruppi = misure.calcola("fatturazione.fatturato", request, per="mese", dal=mesi[0], al=oggi)["gruppi"]
    except ErroreInterrogazione:
        return []
    valori = {g["chiave"]: g["valore"] for g in gruppi}
    return [(f"{MESI[m.month - 1]} {m.year % 100}", float(valori.get(m.isoformat(), 0))) for m in mesi]


def kpi(request):
    """Le stesse misure dell'assistente: il fatturato della dashboard è quello che dice Ada."""
    oggi = timezone.localdate()
    mesi = []
    primo = oggi.replace(day=1)
    for i in range(5, -1, -1):
        anno, mese = divmod(primo.year * 12 + primo.month - 1 - i, 12)
        mesi.append(datetime.date(anno, mese + 1, 1))
    dati = _ultimi_mesi(request, mesi, oggi)
    return {
        "kpi": [{"valore": _euro("fatturazione.fatturato", request, periodo="mese"), "etichetta": "fatturato nel mese (imponibile)"},
                {"valore": _euro("fatturazione.da_incassare", request), "etichetta": "da incassare"},
                {"valore": _euro("fatturazione.scaduto", request), "etichetta": "scaduto"},
                {"valore": queryset(request, Fattura).filter(stato=Fattura.BOZZA).count(), "etichetta": "bozze"}],
        "grafici": [{"titolo": "Fatturato negli ultimi 6 mesi (imponibile, €)", "tipo": "barre",
                     "url": reverse("fatturazione:fatture_grafico"),
                     "dati": dati}] if dati else [],
    }
