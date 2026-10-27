from ninja.errors import HttpError

from core.registry import modules

from . import api
from .auth import azienda_per


def _azienda(a):
    return {"id": a.pk, "nome": a.nome} if a else None


@api.get("/me/", tags=["piattaforma"], summary="Utente, aziende e app visibili")
def me(request):
    from core import azienda
    u = request.user
    corrente = azienda_per(request)
    return {
        "id": u.pk, "username": u.username, "nome": u.get_full_name(), "email": u.email,
        "is_superuser": u.is_superuser,
        "aziende": [_azienda(a) for a in azienda.consentite(u)], "azienda": _azienda(corrente),
        "app": [{"slug": a["slug"], "nome": a["label"], "url": a["url"]} for a in modules.app_visibili(u)],
    }


@api.get("/moduli/", tags=["piattaforma"], summary="Moduli e stato di installazione (superuser)")
def moduli(request):
    if not request.user.is_superuser:
        raise HttpError(403, "solo superuser")
    return [{"slug": m.slug, "nome": m.nome, "stato": m.stato, "versione_installata": m.versione_installata,
             "versione_disponibile": m.versione_disponibile, "application": m.application}
            for m in modules.sincronizza()]
