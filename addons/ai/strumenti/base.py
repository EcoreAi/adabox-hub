"""Strumenti di base, sempre disponibili."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from . import richiesta
from .registro import Strumento, registra

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def data_e_ora(contesto, fuso="Europe/Rome"):
    try:
        zona = ZoneInfo(fuso)
    except (ZoneInfoNotFoundError, ValueError):
        zona = ZoneInfo("Europe/Rome")
    adesso = timezone.now().astimezone(zona)
    return {"data": adesso.date().isoformat(), "ora": adesso.strftime("%H:%M"), "giorno": GIORNI[adesso.weekday()],
            "fuso": str(zona), "settimana_iso": adesso.isocalendar().week}


def app_disponibili(contesto):
    from core.registry import modules
    return [{"app": a["slug"], "nome": a["label"], "descrizione": a.get("summary", ""),
             "sezioni": [v["label"] for v in a["menu"]]} for a in modules.app_visibili(contesto.utente, azienda=contesto.azienda)
            if a["slug"] != "ai"]


MAX_PAGINE = 15


def cerca_pagine(contesto, testo):
    """Le pagine del gestionale che corrispondono a delle parole, con il loro indirizzo: la stessa ricerca di «Cerca
    ovunque» per pagine, voci di menu, grafici e dashboard salvati, con i permessi di chi chiede. Gli indirizzi non
    stanno in app_disponibili: con tutte le sezioni la risposta passerebbe il limite di LIMITE_RISULTATO caratteri."""
    from core import cerca
    gruppi, _ = cerca.scorciatoie(richiesta.per(contesto), testo)
    pagine = [{"titolo": v["titolo"], "url": v["url"], "tipo": v.get("sotto") or g["gruppo"]} for g in gruppi for v in g["voci"]]
    if not pagine:
        return {"pagine": [], "nota": "Nessuna pagina con queste parole: prova con altre, o guarda le sezioni di app_disponibili."}
    return {"pagine": pagine[:MAX_PAGINE]}


registra(Strumento(
    "data_e_ora", "Data, ora, giorno della settimana e settimana ISO correnti (per calcolare scadenze e periodi).",
    {"type": "object", "properties": {"fuso": {"type": "string", "description": "fuso orario IANA, es. Europe/Rome"}},
     "required": []}, data_e_ora))
registra(Strumento(
    "app_disponibili", "Le app del gestionale che l'utente può usare, con le loro sezioni (il link di una sezione lo dà "
                       "cerca_pagine).",
    {"type": "object", "properties": {}, "required": []}, app_disponibili))
registra(Strumento(
    "cerca_pagine", "Trova le pagine del gestionale per parole (es. «statistiche», «nuovo grafico», «utenti», «scadenziario»): "
                    "pagine, voci di menu delle app, grafici e dashboard salvati, con il link. Per dare all'utente il link "
                    "a una pagina; per i dati dentro le app usa cerca_record.",
    {"type": "object", "properties": {"testo": {"type": "string", "description": "le parole da cercare"}}, "required": ["testo"]},
    cerca_pagine))

