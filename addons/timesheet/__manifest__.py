{
    "name": "Timesheet",
    "summary": "Ore lavorate su progetti e compiti, con totali e analisi",
    "version": "1.1.1",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Servizi",
    "depends": ["progetti"],
    "min_core": "1.0",
    "riepilogo": "timesheet.riepilogo.voci",
    "dashboard": "timesheet.dashboard.kpi",
    "application": True,
    "icon": "timesheet/icon.svg",
    "menu": [
        {"label": "Settimana", "url_name": "timesheet:settimana", "permission": "timesheet.add_rigaore"},
        {"label": "Ore", "url_name": "timesheet:ore_lista", "permission": "timesheet.view_rigaore"},
        {"label": "Grafico", "url_name": "timesheet:ore_grafico", "permission": "timesheet.view_rigaore"},
    ],
    "groups": {
        "Timesheet / Utente": ["timesheet.view_rigaore", "timesheet.add_rigaore", "timesheet.change_rigaore",
                               "timesheet.delete_rigaore", "timesheet.view_cronometro", "timesheet.add_cronometro",
                               "timesheet.change_cronometro", "timesheet.delete_cronometro"],
        "Timesheet / Responsabile": ["timesheet.*"],
    },
    "hooks": "timesheet.hooks",
    "settings": [
        {"chiave": "arrotonda_minuti", "label": "Arrotonda il cronometro ai minuti", "tipo": "intero", "default": 15,
         "per_azienda": True, "help": "Per eccesso: 15 = ogni quarto d'ora; 0 = al minuto"},
    ],
}
