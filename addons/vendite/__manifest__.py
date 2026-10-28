{
    "name": "Vendite",
    "summary": "Preventivi e ordini dei clienti, con listini, sconti, IVA, stampa e invio per email",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Vendite",
    "depends": ["prodotti", "contatti"],
    "min_core": "1.0",
    "application": True,
    "icon": "vendite/icon.svg",
    "dashboard": "vendite.dashboard.kpi",
    "menu": [
        {"label": "Preventivi e ordini", "url_name": "vendite:ordini_lista", "permission": "vendite.view_ordinevendita"},
        {"label": "Pipeline", "url_name": "vendite:ordini_kanban", "permission": "vendite.view_ordinevendita"},
        {"label": "Analisi", "url_name": "vendite:ordini_grafico", "permission": "vendite.view_ordinevendita"},
    ],
    "groups": {
        "Vendite / Venditore": ["vendite.view_ordinevendita", "vendite.add_ordinevendita",
                                "vendite.change_ordinevendita", "vendite.view_rigavendita", "vendite.add_rigavendita",
                                "vendite.change_rigavendita", "vendite.delete_rigavendita"],
        "Vendite / Responsabile": ["vendite.*"],
    },
    "hooks": "vendite.hooks",
    "sequences": [
        {"codice": "vendite.preventivo", "formato": "PV/{anno}/{numero:04d}", "azzera": "anno"},
        {"codice": "vendite.ordine", "formato": "OV/{anno}/{numero:04d}", "azzera": "anno"},
    ],
}
