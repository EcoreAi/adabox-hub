{
    "name": "Privacy",
    "summary": "GDPR: consensi dei contatti, richieste degli interessati, esportazione e anonimizzazione dei dati, tempi di conservazione",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Amministrazione",
    "depends": ["contatti"],
    "min_core": "1.0",
    "application": True,
    "icon": "privacy/icon.svg",
    "menu": [
        {"label": "Consensi", "url_name": "privacy:consensi_lista", "permission": "privacy.view_consenso"},
        {"label": "Richieste", "url_name": "privacy:richieste_lista", "permission": "privacy.view_richiestainteressato"},
        {"label": "Finalità", "url_name": "privacy:finalita_lista", "permission": "privacy.change_finalita"},
        {"label": "Conservazione", "url_name": "privacy:conservazione_lista", "permission": "privacy.change_regolaconservazione"},
    ],
    "groups": {
        "Privacy / Operatore": ["privacy.view_consenso", "privacy.add_consenso", "privacy.view_finalita", "privacy.view_richiestainteressato",
                                "privacy.add_richiestainteressato", "privacy.change_richiestainteressato"],
        "Privacy / Responsabile": ["privacy.*"],
    },
    "data": ["data/finalita.json"],
    "cron": [
        {"nome": "Applica i tempi di conservazione", "funzione": "privacy.servizi.applica_conservazione", "ogni": "1d", "alle": "03:15"},
    ],
}
