"""Download delle ricevute (solo per chi vede la nota), spese da riaddebitare ai clienti, rimborso abbinato alla banca."""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core import allegati
from core.dashboard import queryset

from . import flusso, riaddebito
from .models import NotaSpese, RigaSpesa


@login_required
def ricevuta(request, pk):
    riga = get_object_or_404(RigaSpesa, pk=pk, nota__in=queryset(request, NotaSpese))
    if not riga.ricevuta:
        raise Http404
    import mimetypes
    nome = riga.ricevuta.name.rsplit("/", 1)[-1].split("-", 1)[-1]
    finto = type("File", (), {"mime": mimetypes.guess_type(nome)[0] or "application/octet-stream",
                              "file": riga.ricevuta, "nome": nome})()
    return allegati.risposta(finto)


@login_required
@permission_required("fatturazione.add_fattura", raise_exception=True)
def riaddebiti(request):
    """Le spese da rifatturare, per cliente: si scelgono e diventano una fattura in bozza."""
    if not riaddebito.disponibile() or request.azienda is None:
        raise Http404
    if request.method == "POST":
        from contatti.models import Contatto
        cliente = get_object_or_404(Contatto, pk=request.POST.get("cliente") or 0)
        try:
            f = riaddebito.fattura(request.azienda, cliente, [int(p) for p in request.POST.getlist("riga") if p.isdigit()])
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect("spese:riaddebiti")
        messages.success(request, f"Fattura in bozza per {cliente} creata: controlla prezzi e IVA, poi emettila.")
        return redirect("fatturazione:fatture_dettaglio", pk=f.pk)
    gruppi = riaddebito.per_cliente(request.azienda)
    return render(request, "spese/riaddebiti.html", {"gruppi": gruppi, "totale": sum(g["totale"] for g in gruppi)})


@login_required
def rimborso(request, pk):
    """Segna rimborsata una nota approvata, con la data e, se c'è Banca, il movimento che l'ha pagata."""
    nota = get_object_or_404(queryset(request, NotaSpese).select_related("dipendente"), pk=pk)
    if not flusso.gestore(request.user):
        raise PermissionDenied
    if nota.stato != NotaSpese.APPROVATA:
        messages.error(request, "Si rimborsa solo una nota approvata.")
        return redirect("spese:note_dettaglio", pk=nota.pk)
    movimenti = riaddebito.movimenti_per(nota) if request.user.has_perm("banca.view_movimentobanca") else []
    for m in movimenti:
        m.esatto = abs(m.importo) == nota.totale                 # l'importo esatto si propone già scelto
    if request.method == "POST":
        try:
            data = datetime.date.fromisoformat(request.POST.get("data") or "") if request.POST.get("data") else None
        except ValueError:
            data = None
        scelto = next((m for m in movimenti if str(m.pk) == request.POST.get("movimento")), None)
        try:
            with transaction.atomic():
                if scelto is not None:
                    from banca import abbina
                    abbina.abbina_documento(scelto, nota, nota.totale, request.user)
                    data = data or scelto.data
                flusso.rimborsa(nota, request.user, data)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect("spese:rimborso", pk=nota.pk)
        messages.success(request, f"{nota} rimborsata" + (f", abbinata al movimento del {scelto.data:%d/%m/%Y}." if scelto else "."))
        return redirect("spese:note_dettaglio", pk=nota.pk)
    return render(request, "spese/rimborso.html", {"nota": nota, "movimenti": movimenti, "oggi": timezone.localdate(),
                                                   "banca": riaddebito.banca_disponibile()})
