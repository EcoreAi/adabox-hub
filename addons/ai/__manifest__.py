{
    "name": "Assistente AI",
    "summary": "Chat con l'assistente: cronologia delle conversazioni, artifact e documenti salvati",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "ai/icon.svg",
    "home": "ai:chat",
    "menu": [
        {"label": "Chat", "url_name": "ai:chat", "permission": "ai.view_conversazione"},
        {"label": "Profili", "url_name": "ai:profili_lista", "permission": "ai.change_profilo"},
        {"label": "Modelli", "url_name": "ai:modelli_lista", "permission": "ai.change_modello"},
        {"label": "Provider e chiavi", "url_name": "ai:provider_lista", "permission": "ai.change_provider"},
    ],
    "groups": {
        "AI / Utente": ["ai.view_conversazione", "ai.add_conversazione", "ai.change_conversazione",
                        "ai.delete_conversazione"],
        "AI / Amministratore": ["ai.*"],
    },
    "hooks": "ai.hooks",
}
