{
    "name": "Discuss",
    "summary": "Messaggi tra colleghi: canali, messaggi diretti, menzioni e posta in arrivo",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "discuss/icon.svg",
    "dashboard": "discuss.dashboard.kpi",
    "menu": [
        {"label": "Conversazioni", "url_name": "discuss:home", "permission": "discuss.view_canale"},
        {"label": "Posta in arrivo", "url_name": "discuss:posta", "permission": "discuss.view_canale"},
        {"label": "Canali", "url_name": "discuss:canali_lista", "permission": "discuss.change_canale"},
    ],
    "groups": {
        "Discuss / Utente": ["discuss.view_canale", "discuss.add_canale", "discuss.view_messaggio",
                             "discuss.add_messaggio"],
        "Discuss / Responsabile": ["discuss.*"],
    },
    "hooks": "discuss.hooks",
    "cron": [{"nome": "Email dei messaggi non letti", "funzione": "discuss.notifiche.invia_email", "ogni": "10m"}],
}
