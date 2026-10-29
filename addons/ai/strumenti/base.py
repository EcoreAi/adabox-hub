"""Strumenti di base, sempre disponibili."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

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
             "sezioni": [v["label"] for v in a["menu"]]} for a in modules.app_visibili(contesto.utente)
            if a["slug"] != "ai"]


registra(Strumento(
    "data_e_ora", "Data, ora, giorno della settimana e settimana ISO correnti (per calcolare scadenze e periodi).",
    {"type": "object", "properties": {"fuso": {"type": "string", "description": "fuso orario IANA, es. Europe/Rome"}},
     "required": []}, data_e_ora))
registra(Strumento(
    "app_disponibili", "Le app del gestionale che l'utente può usare, con le loro sezioni.",
    {"type": "object", "properties": {}, "required": []}, app_disponibili))

