{
    "name": "Assistente AI",
    "summary": "Chat con l'assistente: cronologia delle conversazioni, artifact e documenti salvati",
    "version": "0.2.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "ai/icon.svg",
    "home": "ai:chat",
    "menu": [
        {"label": "Chat", "url_name": "ai:chat", "permission": "ai.view_conversazione"},
    ],
    "groups": {
        "AI / Utente": ["ai.view_conversazione", "ai.add_conversazione", "ai.change_conversazione",
                        "ai.delete_conversazione"],
    },
    "hooks": "ai.hooks",
}
