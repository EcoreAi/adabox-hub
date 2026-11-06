"""Il caricamento dei pacchetti sul portale, dalla lista dei Pacchetti."""
import tempfile

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render

from core.registry.pacchetti import PacchettoNonValido

from . import servizi


@login_required
@permission_required("rivendita.change_pacchetto", raise_exception=True)
def carica(request):
    if request.method != "POST":
        return render(request, "rivendita/carica.html")
    file = request.FILES.get("pacchetto")
    if file is None:
        messages.error(request, "Scegli un pacchetto .zip.")
        return redirect("rivendita:carica")
    with tempfile.NamedTemporaryFile(suffix=".zip") as temporaneo:
        for blocco in file.chunks():
            temporaneo.write(blocco)
        temporaneo.flush()
        try:
            p = servizi.pubblica(temporaneo.name, nome_file=file.name)
        except PacchettoNonValido as e:
            messages.error(request, "Pacchetto rifiutato: " + "; ".join(e.errori))
            return redirect("rivendita:carica")
    messages.success(request, f"{p.modulo} {p.versione} pubblicato: le istanze licenziate lo ricevono alla prossima sincronizzazione.")
    return redirect("rivendita:pacchetti_lista")
