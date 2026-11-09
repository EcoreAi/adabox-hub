{
    "name": "Parco auto",
    "summary": "I veicoli aziendali: a chi sono assegnati, noleggi e leasing, costi, chilometri e scadenze di assicurazione, bollo e revisione",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Risorse umane",
    "depends": ["personale"],
    "min_core": "1.0",
    "application": True,
    "icon": "flotta/icon.svg",
    "riepilogo": "flotta.riepilogo.voci",
    "menu": [
        {"label": "Veicoli", "url_name": "flotta:veicoli_lista", "permission": "flotta.view_veicolo"},
        {"label": "Costi", "url_name": "flotta:costi_lista", "permission": "flotta.view_costoveicolo"},
        {"label": "Contratti", "url_name": "flotta:contratti_lista", "permission": "flotta.view_contrattoveicolo"},
    ],
    "groups": {
        "Parco auto / Utente": ["flotta.view_veicolo", "flotta.view_costoveicolo", "flotta.add_costoveicolo"],
        "Parco auto / Responsabile": ["flotta.*"],
    },
}
