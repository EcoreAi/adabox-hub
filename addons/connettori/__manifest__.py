{
    "name": "Connettori",
    "summary": "Adabox accanto al software che hai già: avvisi firmati verso l'esterno, collegamenti ai record esterni e HubSpot (persone, aziende, opportunità)",
    "version": "1.2.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Integrazioni",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "connettori/icon.svg",
    "menu": [
        {"label": "Collegamenti", "url_name": "connettori:collegamenti_lista", "permission": "connettori.view_collegamentoesterno"},
        {"label": "Webhook", "url_name": "connettori:webhook_lista", "permission": "connettori.view_webhook"},
        {"label": "Consegne", "url_name": "connettori:consegne_lista", "permission": "connettori.view_consegnawebhook"},
        {"label": "Collegamenti esterni", "url_name": "connettori:riferimenti_lista", "permission": "connettori.view_riferimentoesterno"},
    ],
    "groups": {
        "Connettori / Responsabile": ["connettori.*"],
    },
    "cron": [
        {"nome": "Sincronia con i sistemi esterni", "funzione": "connettori.sincronia.giro_di_tutti", "ogni": "15m"},
        {"nome": "Pulizia delle consegne vecchie", "funzione": "connettori.consegne.pulisci", "ogni": "1d"},
    ],
}
