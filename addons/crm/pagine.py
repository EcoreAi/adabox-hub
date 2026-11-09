"""La pagina dei risultati della vendita."""
import datetime

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.utils import timezone

from . import risultati as motore


def _data(testo, ripiego):
    try:
        return datetime.date.fromisoformat(testo) if testo else ripiego
    except ValueError:
        return ripiego


@login_required
@permission_required("crm.view_opportunita", raise_exception=True)
def risultati(request):
    oggi = timezone.localdate()
    inizio_trimestre = oggi.replace(month=(oggi.month - 1) // 3 * 3 + 1, day=1)
    dal, al = _data(request.GET.get("dal"), inizio_trimestre), _data(request.GET.get("al"), oggi)
    return render(request, "crm/risultati.html", {"dal": dal, "al": al, **motore.risultati(request.azienda, dal, al)})


@login_required
@permission_required("crm.view_opportunita", raise_exception=True)
def previsione(request):
    from decimal import Decimal, InvalidOperation

    from django.contrib import messages
    from django.contrib.auth import get_user_model
    from django.shortcuts import get_object_or_404, redirect

    from . import previsione as motore_previsione
    utente_id = request.GET.get("utente") or request.POST.get("utente") or ""
    utente = get_object_or_404(get_user_model(), pk=utente_id) if utente_id else None
    if request.method == "POST":
        if not request.user.has_perm("crm.change_rettificaprevisione"):
            messages.error(request, "Non puoi rettificare la previsione.")
        else:
            mese = _data(request.POST.get("mese"), None)
            testo = request.POST.get("importo", "").strip().replace(" ", "")
            if "," in testo:                                   # 12.000,50 all'italiana
                testo = testo.replace(".", "").replace(",", ".")
            try:
                importo = Decimal(testo) if testo else None
            except InvalidOperation:
                messages.error(request, "Importo non valido.")
            else:
                if mese:
                    motore_previsione.rettifica(request.azienda, mese, importo, utente, request.POST.get("nota", ""), request.user)
                    messages.success(request, "Rettifica salvata." if importo is not None else "Rettifica tolta.")
        return redirect(request.path + (f"?utente={utente.pk}" if utente else ""))
    righe, totale = motore_previsione.previsione(request.azienda, utente)
    commerciali = get_user_model().objects.filter(opportunita__azienda=request.azienda).distinct().order_by("first_name", "username")
    return render(request, "crm/previsione.html", {"righe": righe, "totale": totale, "utente": utente, "commerciali": commerciali,
                                                   "puo_rettificare": request.user.has_perm("crm.change_rettificaprevisione")})
