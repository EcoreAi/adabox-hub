from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, voce

from .models import Veicolo


def voci(request, dal, oggi):
    if not request.user.has_perm("flotta.view_veicolo"):
        return [voce(ATTENZIONE, 0, "scadenza di un veicolo", "scadenze dei veicoli")]
    righe = []
    for v in queryset(request, Veicolo).filter(attivo=True):
        for nome, data, scaduta in v.scadenze(30, oggi):
            righe.append((f"{v.targa} · {nome}" + (f" il {data:%d/%m}" if data else "") + (" (scaduta)" if scaduta else ""),
                          reverse("flotta:veicoli_dettaglio", args=[v.pk])))
    return [voce(ATTENZIONE, len(righe), "scadenza di un veicolo", "scadenze dei veicoli", reverse("flotta:veicoli_lista"), dettagli=righe[:5])]
