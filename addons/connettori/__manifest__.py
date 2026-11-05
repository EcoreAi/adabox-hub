{
    "name": "Connettori",
    "summary": "Adabox accanto al software che hai già: avvisi firmati verso l'esterno e collegamenti ai record dei sistemi esterni",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Integrazioni",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "connettori/icon.svg",
    "menu": [
        {"label": "Webhook", "url_name": "connettori:webhook_lista", "permission": "connettori.view_webhook"},
        {"label": "Consegne", "url_name": "connettori:consegne_lista", "permission": "connettori.view_consegnawebhook"},
        {"label": "Collegamenti esterni", "url_name": "connettori:riferimenti_lista", "permission": "connettori.view_riferimentoesterno"},
    ],
    "groups": {
        "Connettori / Responsabile": ["connettori.*"],
    },
    "cron": [
        {"nome": "Pulizia delle consegne vecchie", "funzione": "connettori.consegne.pulisci", "ogni": "1d"},
    ],
}
