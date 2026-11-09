{
    "name": "Automazioni",
    "summary": "Quando succede qualcosa, fallo da solo: solleciti, promemoria, assegnazioni e i modelli delle email",
    "version": "1.1.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "automazioni/icon.svg",
    "menu": [
        {"label": "Regole", "url_name": "automazioni:regole", "permission": "automazioni.view_regola"},
        {"label": "Modelli email", "url_name": "automazioni:modelli", "permission": "core.view_modelloemail"},
        {"label": "Storico", "url_name": "automazioni:storico", "permission": "automazioni.view_regola"},
    ],
    "groups": {
        "Automazioni / Responsabile": ["automazioni.*", "core.view_modelloemail", "core.add_modelloemail",
                                       "core.change_modelloemail", "core.delete_modelloemail"],
    },
    "cron": [
        {"nome": "Regole a tempo", "funzione": "automazioni.motore.controlla_tempo", "ogni": "1h"},
    ],
}
