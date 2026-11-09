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
