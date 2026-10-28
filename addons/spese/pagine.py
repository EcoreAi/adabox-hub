"""Download delle ricevute (solo per chi vede la nota)."""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404

from core import allegati
from core.dashboard import queryset

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
