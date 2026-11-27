"""Dove si apre l'app installata: la scelta della persona nel profilo, o la scorciatoia dell'icona (?apri=).
E la prima pagina che chi amministra sceglie per un ruolo o per una persona: dove si arriva dopo l'accesso (core.views.home)
e, se la persona non ha una scelta sua, aprendo l'app installata."""
from django.urls import NoReverseMatch, reverse

DESTINAZIONI = {"parla": ("ai:parla", "ai.add_conversazione"), "chat": ("ai:chat", "ai.add_conversazione")}
PAGINE_DEL_KERNEL = [("core:dashboard", "Dashboard"), ("core:tasca", "In tasca")]


def pagine_possibili():
    """[(nome URL, etichetta)] tra cui scegliere una prima pagina: le pagine del kernel e le voci di menu delle app
    attive («Vendite · Ordini»)."""
    from core.registry import modules
    spenti, nomi = modules.disattivati(), modules.etichette()
    voci = list(PAGINE_DEL_KERNEL)
    for slug, m in modules.manifests_attivi().items():
        if m.application and slug not in spenti:
            voci += [(v["url_name"], f"{nomi.get(slug) or m.name} · {v['label']}") for v in m.menu]
    return voci


def prima_pagina(utente):
    """L'indirizzo della prima pagina scelta da chi amministra per questa persona (sul suo profilo) o per il suo ruolo.
    None se non c'è una scelta o se la persona quella pagina non la può aprire (permesso, app spenta o di un'altra
    azienda, fuori dai suoi dipartimenti): allora vale la barra in alto, come senza scelta."""
    from core.registry import modules
    profilo = getattr(utente, "profilo", None)
    if profilo is None:
        return None
    nome = profilo.prima_pagina or (profilo.ruolo.prima_pagina if profilo.ruolo_id else "")
    if not nome:
        return None
    if nome not in dict(PAGINE_DEL_KERNEL) and nome not in {v["url_name"] for a in modules.app_visibili(utente) for v in a["menu"]}:
        return None
    try:
        return reverse(nome)
    except NoReverseMatch:
        return None


def destinazione(utente, scelta):
    """L'indirizzo della pagina scelta, se esiste (modulo installato) e la persona la può usare; None altrimenti."""
    voce = DESTINAZIONI.get(scelta or "")
    if voce is None or not utente.has_perm(voce[1]):
        return None
    try:
        return reverse(voce[0])
    except NoReverseMatch:
        return None
