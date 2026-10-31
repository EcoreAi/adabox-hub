{
    "name": "Agate",
    "summary": "Le modifiche dell'assistente AI passano dalle regole e dalle approvazioni di Agate; i modelli dal suo proxy",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": ["ai"],
    "min_core": "1.0",
    "application": True,
    "icon": "agate/icon.svg",
    "home": "agate:collegamento",
    "menu": [
        {"label": "Collegamento", "url_name": "agate:collegamento", "permission": "agate.change_collegamento"},
        {"label": "Valutazioni", "url_name": "agate:valutazioni", "permission": "agate.view_valutazione"},
    ],
    "groups": {
        "Agate / Amministratore": ["agate.*"],
    },
    "cron": [
        {"nome": "Esito delle approvazioni in Agate", "funzione": "agate.lavori.controlla_approvazioni", "ogni": "1m"},
    ],
}
