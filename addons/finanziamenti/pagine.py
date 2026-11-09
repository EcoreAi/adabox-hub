"""Pagamento di una rata (anche abbinato al movimento di banca) ed estinzione anticipata."""
import datetime
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import piano
from .models import Finanziamento, RataFinanziamento


def _data(testo):
    try:
        return datetime.date.fromisoformat(testo) if testo else None
    except ValueError:
        return None


def _azienda(request):
    return getattr(getattr(request, "azienda", None), "pk", None)


@login_required
@permission_required("finanziamenti.change_ratafinanziamento", raise_exception=True)
def paga(request, pk):
    rata = get_object_or_404(RataFinanziamento.objects.select_related("finanziamento"), pk=pk, azienda_id=_azienda(request))
    banca = apps.is_installed("banca") and request.user.has_perm("banca.view_movimentobanca")
    movimenti = []
    if banca and not rata.pagata:
        from banca import abbina
        movimenti = abbina.candidati_uscita(rata.finanziamento.azienda, rata.importo, rata.data)
        for m in movimenti:
            m.esatto = abs(m.importo) == rata.importo
    if request.method == "POST":
        scelto = next((m for m in movimenti if str(m.pk) == request.POST.get("movimento")), None)
        try:
            piano.paga(rata, _data(request.POST.get("data")) or (None if scelto else timezone.localdate()), request.user, scelto)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect("finanziamenti:paga", pk=rata.pk)
        messages.success(request, f"Rata {rata.numero} pagata.")
        return redirect("finanziamenti:finanziamenti_dettaglio", pk=rata.finanziamento_id)
    return render(request, "finanziamenti/paga.html", {"rata": rata, "movimenti": movimenti, "banca": banca,
                                                       "oggi": timezone.localdate()})


@login_required
@permission_required("finanziamenti.change_finanziamento", raise_exception=True)
def estingui(request, pk):
    f = get_object_or_404(Finanziamento, pk=pk, azienda_id=_azienda(request))
    if request.method == "POST":
        try:
            penale = Decimal(request.POST.get("penale") or 0)
        except InvalidOperation:
            penale = None
        data = _data(request.POST.get("data"))
        if data is None or penale is None or penale < 0:
            messages.error(request, "Indica la data e una penale valida (anche zero).")
        else:
            try:
                rata = piano.estingui(f, data, penale, request.user)
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
            else:
                messages.success(request, f"Rata di estinzione di {rata.importo} € al {data:%d/%m/%Y}: segnala pagata quando parte.")
                return redirect("finanziamenti:finanziamenti_dettaglio", pk=f.pk)
    return render(request, "finanziamenti/estingui.html", {"f": f, "residuo": f.debito_residuo(), "oggi": timezone.localdate()})
