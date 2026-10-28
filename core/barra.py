"""Barra in alto: quali app restano visibili (scelte dall'amministratore) e quante, le altre vanno in "Altre"."""
from django.conf import settings

from .models import Parametro

CHIAVE = "core.barra"
MASSIMO = 12


def leggi():
    """{"fisse": [slug, ...] in ordine, "quante": n} — con i default se l'amministratore non ha scelto."""
    p = Parametro.objects.filter(chiave=CHIAVE, azienda__isnull=True).first()
    valore = p.valore if p is not None and isinstance(p.valore, dict) else {}
    fisse = [s for s in valore.get("fisse", []) if isinstance(s, str)]
    quante = valore.get("quante")
    if not isinstance(quante, int) or not 1 <= quante <= MASSIMO:
        quante = settings.NAV_APP_VISIBILI
    return {"fisse": fisse, "quante": quante}


def scrivi(fisse, quante):
    Parametro.objects.update_or_create(chiave=CHIAVE, azienda=None, defaults={
        "valore": {"fisse": list(fisse), "quante": max(1, min(MASSIMO, int(quante)))}})


def dividi(voci_app, corrente=None, quante=None, fisse=None):
    """(principali, altre). Con app fisse: quelle, nell'ordine scelto (se l'utente le vede); altrimenti le prime
    `quante`. L'app in cui si trova l'utente è sempre tra le principali (al posto dell'ultima)."""
    quante = settings.NAV_APP_VISIBILI if quante is None else quante
    posizione = {v["slug"]: i for i, v in enumerate(voci_app)}
    if fisse:
        per_slug = {v["slug"]: v for v in voci_app}
        principali = [per_slug[s] for s in fisse if s in per_slug]
        altre = [v for v in voci_app if v["slug"] not in set(fisse)]
    else:
        if len(voci_app) <= quante + 1:                   # una sola in più: inutile un menu per lei
            return voci_app, []
        principali, altre = voci_app[:quante], voci_app[quante:]
    slug = corrente["slug"] if corrente else None
    attiva = next((v for v in altre if v["slug"] == slug), None)
    if attiva is not None:
        altre = [v for v in altre if v is not attiva]
        if principali and len(principali) >= (len(fisse) if fisse else quante):     # barra piena: cede l'ultima
            altre = sorted([*altre, principali[-1]], key=lambda v: posizione[v["slug"]])
            principali = principali[:-1]
        principali = [*principali, attiva]
    return principali, altre
