"""La chiusura della cassa: saldo atteso, contanti contati, differenza."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.dashboard import queryset

from . import operazioni
from .models import Cassa


@login_required
@permission_required("cassa.add_chiusuracassa", raise_exception=True)
def chiudi(request, pk):
    cassa = get_object_or_404(queryset(request, Cassa), pk=pk)
    oggi = timezone.localdate()
    data, contato, nota = oggi, "", ""
    if request.method == "POST":
        nota = request.POST.get("nota", "").strip()
        try:
            data = timezone.datetime.fromisoformat(request.POST.get("data", "")).date()
        except ValueError:
            data = oggi
        contato = request.POST.get("contato", "").replace(",", ".").strip()
        try:
            chiusura = operazioni.chiudi(cassa, data, Decimal(contato), request.user, nota)
        except (InvalidOperation, ValueError):
            messages.error(request, "Scrivi i contanti contati, per esempio 152,30.")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            if chiusura.differenza:
                cosa = "un'eccedenza" if chiusura.differenza > 0 else "un ammanco"
                messages.warning(request, f"Cassa chiusa con {cosa} di {abs(chiusura.differenza)} €, registrato come movimento.")
            else:
                messages.success(request, "Cassa chiusa: i conti tornano.")
            return redirect("cassa:casse_dettaglio", pk=cassa.pk)
    precedente = cassa.ultima_chiusura()
    return render(request, "cassa/chiudi.html", {
        "cassa": cassa, "data": data, "contato": contato, "nota": nota, "precedente": precedente,
        "atteso": cassa.saldo_al(data), "apertura": precedente.contato if precedente else cassa.saldo_iniziale,
        "aperti": cassa.movimenti.filter(chiusura__isnull=True, data__lte=data).order_by("data", "pk")})
