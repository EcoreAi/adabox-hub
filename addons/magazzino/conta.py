"""La pagina della conta di un inventario: contato riga per riga, importazione CSV, approvazione."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from core.dashboard import queryset

from . import inventari
from .models import Inventario


@login_required
@permission_required("magazzino.view_inventario", raise_exception=True)
def conta(request, pk):
    inv = get_object_or_404(queryset(request, Inventario).select_related("magazzino", "ubicazione"), pk=pk)
    if request.method == "POST":
        azione = request.POST.get("azione", "salva")
        try:
            if azione == "approva":
                if not request.user.has_perm("magazzino.add_movimento"):
                    raise ValidationError("Per approvare serve il permesso di rettificare il magazzino.")
                inventari.scrivi(inv, _valori(request))
                inventari.approva(inv, request.user, request.POST.get("zero") == "1")
                messages.success(request, "Inventario approvato: le differenze sono diventate rettifiche.")
            elif azione == "importa":
                file = request.FILES.get("file")
                if file is None:
                    raise ValidationError("Scegli il file da importare.")
                letti, scartati = inventari.importa(inv, file.read())
                messages.success(request, f"Contato importato per {letti} prodotti.")
                if scartati:
                    messages.warning(request, "Non trovati o con più lotti: " + ", ".join(scartati[:20]) + ("…" if len(scartati) > 20 else ""))
            else:
                if not request.user.has_perm("magazzino.change_inventario"):
                    raise ValidationError("Non puoi scrivere il contato.")
                inventari.scrivi(inv, _valori(request))
                messages.success(request, "Contato salvato.")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        return redirect("magazzino:inventario_conta", pk=inv.pk)
    righe = list(inv.righe.select_related("prodotto", "lotto"))
    contate = [r for r in righe if r.contato is not None]
    cieca = inv.stato == Inventario.CONTA and request.GET.get("teorico") != "1"
    return render(request, "magazzino/conta.html", {
        "inv": inv, "righe": righe, "contate": len(contate), "cieca": cieca,
        "diverse": sum(1 for r in contate if r.differenza), "puo_scrivere": request.user.has_perm("magazzino.change_inventario"),
        "valore": sum((r.valore_rettifica or 0) for r in righe)})


def _valori(request):
    return {int(k[2:]): v for k, v in request.POST.items() if k.startswith("c_") and k[2:].isdigit()}
