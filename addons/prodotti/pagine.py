"""Immagini dei prodotti, solo per chi vede il prodotto."""
import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.views.decorators.http import require_GET

from core.dashboard import queryset

from . import immagini
from .models import ImmagineProdotto, Prodotto


def _visibile(request, nome):
    visibili = queryset(request, Prodotto)
    return (visibili.filter(immagine=nome).exists()
            or ImmagineProdotto.objects.filter(file=nome, prodotto__in=visibili).exists())


@require_GET
@login_required
def immagine(request, nome):
    """L'immagine (o la sua miniatura con ?lato=64|200|600). Il nome è casuale e non cambia: si tiene in cache."""
    if not nome or not _visibile(request, nome) or not immagini.storage.exists(nome):
        raise Http404
    lato = request.GET.get("lato", "")
    if lato:
        if not lato.isdigit() or int(lato) not in immagini.LATI:
            raise Http404
        percorso = immagini.miniatura(nome, int(lato))
    else:
        percorso = Path(immagini.storage.path(nome))
    tipo = mimetypes.guess_type(str(percorso))[0] or "application/octet-stream"
    if settings.ALLEGATI_X_ACCEL:
        relativo = percorso.relative_to(immagini.storage.location)
        r = HttpResponse(content_type=tipo)
        r["X-Accel-Redirect"] = f"/_privati/{relativo}"
    else:
        r = FileResponse(open(percorso, "rb"), content_type=tipo)
    r["Cache-Control"] = "private, max-age=604800, immutable"
    return r
