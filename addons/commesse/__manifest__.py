{
    "name": "Commesse",
    "summary": "Dalle ore alla fattura: tariffe e costi, ore sui ticket, monte ore dei contratti, redditività dei progetti",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Servizi",
    "depends": ["timesheet", "fatturazione", "assistenza"],
    "min_core": "1.0",
    "application": True,
    "icon": "commesse/icon.svg",
    "menu": [
        {"label": "Da fatturare", "url_name": "commesse:da_fatturare", "permission": "commesse.view_condizioni"},
        {"label": "Condizioni dei progetti", "url_name": "commesse:condizioni_lista", "permission": "commesse.view_condizioni"},
        {"label": "Costi orari", "url_name": "commesse:costi_lista", "permission": "commesse.view_costoorario"},
    ],
    "groups": {
        "Commesse / Utente": ["commesse.view_condizioni", "commesse.view_tariffapersona", "commesse.view_oreticket",
                              "commesse.add_oreticket"],
        "Commesse / Responsabile": ["commesse.*", "fatturazione.view_fattura", "fatturazione.add_fattura",
                                    "fatturazione.add_rigafattura"],
    },
    "hooks": "commesse.hooks",
    "settings": [
        {"chiave": "solo_approvate", "label": "Fattura solo le ore approvate", "tipo": "booleano", "default": False,
         "per_azienda": True, "help": "Le ore non approvate non compaiono tra quelle da fatturare"},
    ],
}
