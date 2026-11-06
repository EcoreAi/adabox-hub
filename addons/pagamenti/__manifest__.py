{
    "name": "Pagamenti online",
    "summary": "«Paga ora» sulle fatture: il cliente paga con carta dal portale o da un link, e l'incasso si registra da solo",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Amministrazione",
    "depends": ["fatturazione"],
    "min_core": "1.0",
    "application": True,
    "icon": "pagamenti/icon.svg",
    "menu": [
        {"label": "Pagamenti", "url_name": "pagamenti:pagamenti_lista", "permission": "pagamenti.view_pagamento"},
        {"label": "Fornitori", "url_name": "pagamenti:fornitori_lista", "permission": "pagamenti.change_fornitorepagamento"},
    ],
    "groups": {
        "Pagamenti / Amministrazione": ["pagamenti.view_pagamento", "pagamenti.view_fornitorepagamento"],
        "Pagamenti / Gestore": ["pagamenti.*"],
    },
}
