"""Barra in alto: quali app restano visibili (scelte dall'amministratore) e quante, le altre vanno in "Altre"."""
from django.conf import settings

from .models import Parametro

CHIAVE = "core.barra"
MASSIMO = 12


def leggi():
    """{"fisse": [slug, ...] in ordine, "quante": n, "nascoste": [slug, ...], "completa": bool} — con i default se
    l'amministratore non ha scelto. «Completa»: `fisse` comprende anche Chat e Dashboard, che altrimenti stanno per prime."""
    p = Parametro.objects.filter(chiave=CHIAVE, azienda__isnull=True).first()
    valore = p.valore if p is not None and isinstance(p.valore, dict) else {}
    fisse = [s for s in valore.get("fisse", []) if isinstance(s, str)]
    quante = valore.get("quante")
    if not isinstance(quante, int) or not 1 <= quante <= MASSIMO:
        quante = settings.NAV_APP_VISIBILI
    return {"fisse": fisse, "quante": quante, "nascoste": _slug(valore.get("nascoste")), "completa": bool(valore.get("completa"))}


def _slug(lista):
    return [s for s in lista if isinstance(s, str)] if isinstance(lista, list) else []


def per_utente(utente):
    """La scelta della persona, se ne ha fatta una; altrimenti quella dell'azienda."""
    from .models import ProfiloUtente
    aziendale = leggi()
    propria = ProfiloUtente.objects.filter(utente=utente).values_list("barra", flat=True).first() or {}
    if not propria.get("completa") and not propria.get("fisse"):
        return aziendale
    return {"fisse": _slug(propria.get("fisse")), "quante": aziendale["quante"], "nascoste": _slug(propria.get("nascoste")), "completa": bool(propria.get("completa"))}


def scrivi(fisse, quante, nascoste=()):
    Parametro.objects.update_or_create(chiave=CHIAVE, azienda=None, defaults={
        "valore": {"fisse": list(fisse), "quante": max(1, min(MASSIMO, int(quante))), "nascoste": list(nascoste), "completa": True}})


def voci(apps):
    """(voci delle app, voce della Dashboard) da `modules.app_visibili`: le stesse per la barra e per la prima pagina."""
    voci_app = [{"label": a["nav_label"], "url_name": a["url_name"], "slug": a["slug"], "categoria": a["category"]} for a in apps]
    return voci_app, {"label": "Dashboard", "url_name": "core:dashboard", "slug": DASHBOARD, "categoria": "Direzione"}


def prima_pagina(utente, apps):
    """Il nome URL della prima voce della barra come la vede l'utente (la sua scelta o quella dell'azienda)."""
    voci_app, dashboard = voci(apps)
    principali, _ = componi(voci_app, dashboard, per_utente(utente))
    return [v["url_name"] for v in principali] or [dashboard["url_name"]]


def componi(voci_app, dashboard, scelta, corrente=None):
    """(barra, altre) come le vede l'utente. Con una scelta completa ogni voce sta dove è stata messa, Chat e Dashboard
    comprese; altrimenti quelle restano per prime. Le nascoste escono da entrambe, tranne l'app in cui si trova."""
    if scelta.get("completa"):
        tutte = [dashboard, *voci_app]
        fisse = scelta["fisse"]
        per_slug = {v["slug"]: v for v in tutte}
        principali, altre = [per_slug[s] for s in fisse if s in per_slug], [v for v in tutte if v["slug"] not in set(fisse)]
        slug = corrente["slug"] if corrente else None
        attiva = next((v for v in altre if v["slug"] == slug), None)
        if attiva is not None:                            # l'app aperta resta sempre visibile
            altre.remove(attiva)
            principali.append(attiva)
    else:
        prime, resto = in_testa(voci_app)
        principali, altre = dividi(resto, corrente, scelta["quante"], scelta["fisse"])
        principali = [*prime, dashboard, *principali]
    via = set(scelta.get("nascoste") or []) - {corrente["slug"] if corrente else None}
    return [v for v in principali if v["slug"] not in via], [v for v in altre if v["slug"] not in via]


# Le colonne del menu «Altre»: raggruppano le categorie dei manifest, in quest'ordine. Dentro, ordine alfabetico.
DASHBOARD = "dashboard"
COLONNE = [("Vendite e clienti", {"Vendite", "Anagrafiche"}), ("Acquisti e magazzino", {"Acquisti", "Magazzino"}),
           ("Amministrazione", {"Contabilità"}), ("Progetti e assistenza", {"Servizi"}), ("Persone", {"Risorse umane"}),
           ("Collaborazione", {"Produttività", "Assistente"}), ("Direzione e strumenti", {"Direzione", "Strumenti"})]
ALTRE_APP = "Altre app"


def colonna_di(categoria):
    return next((nome for nome, categorie in COLONNE if categoria in categorie), ALTRE_APP)


def gruppi(voci, etichetta="label"):
    """[{"titolo", "voci"}] per colonna, senza quelle vuote: le app di una categoria nuova vanno in «Altre app»."""
    risultato = {nome: [] for nome, _ in COLONNE} | {ALTRE_APP: []}
    for v in voci:
        risultato[colonna_di(v.get("categoria", ""))].append(v)
    return [{"titolo": t, "voci": sorted(vs, key=lambda v: str(v[etichetta]).lower())} for t, vs in risultato.items() if vs]


def in_testa(voci_app):
    """(app sempre per prime, nell'ordine di NAV_APP_IN_TESTA; tutte le altre)."""
    ordine = list(getattr(settings, "NAV_APP_IN_TESTA", []))
    prime = sorted((v for v in voci_app if v["slug"] in ordine), key=lambda v: ordine.index(v["slug"]))
    return prime, [v for v in voci_app if v["slug"] not in ordine]


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
