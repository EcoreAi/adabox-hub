{
    "name": "To-Do",
    "summary": "Attività personali e di squadra con scadenze",
    "version": "1.2.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "todo/icon.svg",
    "menu": [
        {"label": "Attività", "url_name": "todo:attivita_lista", "permission": "todo.view_attivita"},
        {"label": "Tag", "url_name": "todo:tag_lista", "permission": "todo.view_tag"},
    ],
    "groups": {
        "To-Do / Utente": ["todo.view_attivita", "todo.add_attivita", "todo.change_attivita", "todo.view_tag"],
        "To-Do / Responsabile": ["todo.*"],
    },
    "data": ["data/tag.json"],
    "demo": ["data/demo.json"],
    "hooks": "todo.hooks",
    "settings_url": None,
    "cron": [
        {"nome": "Promemoria scadenze", "funzione": "todo.lavori.promemoria_scadenze", "ogni": "1d", "alle": "07:30"},
    ],
    "settings": [
        {"chiave": "giorni_preavviso", "label": "Giorni di preavviso", "tipo": "intero", "default": 2,
         "per_azienda": True, "help": "Quanti giorni prima della scadenza l'assegnatario riceve il promemoria"},
    ],
    "sequences": [
        {"codice": "todo.attivita", "formato": "ATT/{anno}/{numero:04d}", "azzera": "anno"},
    ],
}
