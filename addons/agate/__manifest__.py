{
    "name": "Agate",
    "summary": "Le modifiche dell'assistente AI passano dalle regole e dalle approvazioni di Agate; i modelli dal suo proxy",
    "version": "1.0.1",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": ["ai"],
    "min_core": "1.0",
    "riepilogo": "agate.riepilogo.voci",
    "application": False,
    "icon": "agate/icon.svg",
    "menu_profilo": [
        {"label": "Controllo AI", "url_name": "agate:stato", "permission": "agate.change_collegamento",
         "icon": "shield"},
        {"label": "Da approvare", "url_name": "agate:da_approvare", "permission": "agate.change_collegamento",
         "icon": "inbox", "conteggio": "agate.decisioni.conteggio"},
    ],
    "groups": {
        "Agate / Amministratore": ["agate.*"],
    },
    "cron": [
        {"nome": "Esito delle approvazioni in Agate", "funzione": "agate.lavori.controlla_approvazioni", "ogni": "1m"},
    ],
}
