{
    "name": "Qualità",
    "summary": "Collaudi dei progetti: casi di test, ambienti, esecuzioni ed esiti, difetti aperti come compiti",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Servizi",
    "depends": ["progetti"],
    "min_core": "1.0",
    "application": True,
    "icon": "qualita/icon.svg",
    "menu": [
        {"label": "Collaudi", "url_name": "qualita:collaudi_lista", "permission": "qualita.view_collaudo"},
        {"label": "Casi di test", "url_name": "qualita:casi_lista", "permission": "qualita.view_casotest"},
        {"label": "Ambienti", "url_name": "qualita:ambienti_lista", "permission": "qualita.view_ambiente"},
    ],
    "groups": {
        "Qualità / Tester": ["qualita.view_collaudo", "qualita.view_casotest", "qualita.view_ambiente",
                             "qualita.view_esecuzione", "qualita.change_esecuzione", "qualita.add_casotest",
                             "qualita.change_casotest", "progetti.add_compito"],
        "Qualità / Responsabile": ["qualita.*", "progetti.add_compito"],
    },
}
