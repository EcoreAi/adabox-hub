{
    "name": "Cassa",
    "summary": "Casse e piccola cassa: entrate e uscite in contanti, chiusura con il contato e la differenza, incassi e rimborsi in contanti già dentro",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Contabilità",
    "depends": ["fatturazione"],
    "min_core": "1.0",
    "application": True,
    "icon": "cassa/icon.svg",
    "menu": [
        {"label": "Casse", "url_name": "cassa:casse_lista", "permission": "cassa.view_cassa"},
        {"label": "Movimenti", "url_name": "cassa:movimenti_lista", "permission": "cassa.view_movimentocassa"},
        {"label": "Chiusure", "url_name": "cassa:chiusure_lista", "permission": "cassa.view_chiusuracassa"},
    ],
    "groups": {
        "Cassa / Utente": ["cassa.view_cassa", "cassa.view_movimentocassa", "cassa.add_movimentocassa", "cassa.change_movimentocassa",
                           "cassa.view_chiusuracassa"],
        "Cassa / Responsabile": ["cassa.*"],
    },
}
