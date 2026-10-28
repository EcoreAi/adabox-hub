{
    "name": "Studio",
    "summary": "Adatta le viste senza programmare: colonne, filtri, form, etichette e campi nuovi",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Strumenti",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "studio/icon.svg",
    "dashboard": "studio.dashboard.kpi",
    "menu": [
        {"label": "Viste", "url_name": "studio:indice", "permission": "studio.change_personalizzazione"},
        {"label": "Campi personalizzati", "url_name": "core:campi_lista", "permission": "core.view_campopersonalizzato"},
    ],
    "groups": {
        "Studio / Amministratore": ["studio.*", "core.view_campopersonalizzato", "core.add_campopersonalizzato",
                                    "core.change_campopersonalizzato", "core.delete_campopersonalizzato"],
    },
}
