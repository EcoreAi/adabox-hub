{
    "name": "Analitica",
    "summary": "Centri di costo, commesse e altri assi su righe di fatture, fatture ricevute e note spese, con ripartizioni, budget e report per asse",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Contabilità",
    "depends": ["fatturazione"],
    "min_core": "1.0",
    "application": True,
    "icon": "analitica/icon.svg",
    "menu": [
        {"label": "Report per asse", "url_name": "analitica:report", "permission": "analitica.view_imputazione"},
        {"label": "Imputa le righe", "url_name": "analitica:imputa", "permission": "analitica.add_imputazione"},
        {"label": "Budget", "url_name": "analitica:budget_lista", "permission": "analitica.view_budget"},
        {"label": "Voci", "url_name": "analitica:voci_lista", "permission": "analitica.view_voce"},
        {"label": "Assi", "url_name": "analitica:assi_lista", "permission": "analitica.change_asse"},
        {"label": "Modelli di ripartizione", "url_name": "analitica:modelli_lista", "permission": "analitica.view_modelloripartizione"},
    ],
    "groups": {
        "Analitica / Lettura": ["analitica.view_asse", "analitica.view_voce", "analitica.view_imputazione", "analitica.view_budget",
                                "analitica.view_rigabudget", "analitica.view_modelloripartizione", "analitica.view_rigamodello"],
        "Analitica / Responsabile": ["analitica.*"],
    },
}
