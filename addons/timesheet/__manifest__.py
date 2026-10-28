{
    "name": "Timesheet",
    "summary": "Ore lavorate su progetti e compiti, con totali e analisi",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Servizi",
    "depends": ["progetti"],
    "min_core": "1.0",
    "application": True,
    "icon": "timesheet/icon.svg",
    "menu": [
        {"label": "Settimana", "url_name": "timesheet:settimana", "permission": "timesheet.add_rigaore"},
        {"label": "Ore", "url_name": "timesheet:ore_lista", "permission": "timesheet.view_rigaore"},
        {"label": "Analisi", "url_name": "timesheet:ore_grafico", "permission": "timesheet.view_rigaore"},
    ],
    "groups": {
        "Timesheet / Utente": ["timesheet.view_rigaore", "timesheet.add_rigaore", "timesheet.change_rigaore",
                               "timesheet.delete_rigaore"],
        "Timesheet / Responsabile": ["timesheet.*"],
    },
    "hooks": "timesheet.hooks",
}
