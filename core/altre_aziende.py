"""App delle altre aziende dell'utente, per la barra in alto: chi lavora in più aziende trova anche le app che avrebbe in
barra nelle altre (es. riservate a quelle con Modulo.aziende) e ci passa con un clic.

Il clic lo fa il meccanismo di cambio del tema, riusabile da ogni pagina: un link con `data-cambia-azienda="<pk>"`, il
form nascosto di `theme/partials/_cambia_azienda.html` (POST a core:cambia_azienda) e `theme/cambia_azienda.js`, che al
clic scrive azienda e indirizzo nel form e lo invia. Senza script il link apre la pagina dell'altra azienda, che
risponde «Passa a …» (core.middleware)."""
from django.conf import settings

from . import azienda as az
from . import barra
from .registry import hooks, modules

_MEMO = "_voci_altre_aziende"


def voci(request, visibili=None):
    """[{slug, label, url, azienda_pk, azienda_nome, solo_computer}]: per ogni altra azienda consentita (per nome), le
    app che lì avrebbe in barra e che con l'azienda corrente non vede; un'app di più aziende una volta sola, per la
    prima. `label` e `url` come la barra: etichetta dell'istanza (o nome del manifest) e prima pagina permessa.
    Calcolate una volta per richiesta; `visibili` sono le app dell'azienda corrente, se chi chiama le ha già."""
    memo = getattr(request, _MEMO, None)
    if memo is None:
        memo = _calcola(request, visibili)
        setattr(request, _MEMO, memo)
    return memo


def _calcola(request, visibili):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return []
    aziende = az.consentite(user)
    if len(aziende) < 2:                                     # una sola azienda: nient'altro da guardare
        return []
    corrente = getattr(request, "azienda", None)
    if visibili is None:
        visibili = modules.app_visibili(user, corrente)
    # come la barra: niente app nascoste dalla scelta della barra, niente app che sono schede della Dashboard
    fuori = {a["slug"] for a in visibili} | set(barra.per_utente(user)["nascoste"]) | hooks.parti_dashboard()
    solo_computer = set(getattr(settings, "NAV_SOLO_COMPUTER", ()))
    risultato = []
    for altra in (a for a in aziende if a != corrente):        # consentite sono già in ordine di nome
        for app in modules.app_visibili(user, altra):
            if app["slug"] in fuori:
                continue
            fuori.add(app["slug"])
            risultato.append({"slug": app["slug"], "label": app["nav_label"], "url": app["url"], "azienda_pk": altra.pk,
                              "azienda_nome": altra.nome, "solo_computer": app["slug"] in solo_computer})
    return risultato
