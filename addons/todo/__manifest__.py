{
    "name": "To-Do",
    "summary": "Attività personali e di squadra con scadenze",
    "version": "1.0.0",
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
}
