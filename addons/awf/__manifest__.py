{
    "name": "Agentic Workforce",
    "summary": "Agenti AI in affitto che lavorano nel gestionale, con Agate come garante delle loro azioni",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": ["ai"],
    "min_core": "1.0",
    "application": True,
    "nav_label": "Agenti",
    "icon": "awf/icon.svg",
    "home": "awf:stato",
    "menu": [
        {"label": "Stato e collegamento", "url_name": "awf:stato", "permission": "awf.change_collegamento"},
        {"label": "Agenti", "url_name": "awf:agenti", "permission": "awf.view_agente"},
        {"label": "Operazioni ammesse", "url_name": "awf:operazioni", "permission": "awf.view_operazioneammessa"},
        {"label": "Approvazioni in attesa", "url_name": "awf:approvazioni", "permission": "awf.view_approvazione"},
    ],
    "groups": {
        "AWF / Amministratore": ["awf.*"],
    },
    "hooks": "awf.hooks",
    "cron": [
        {"nome": "Battito verso la fabbrica degli agenti", "funzione": "awf.lavori.battito", "ogni": "15m"},
    ],
    "settings": [
        {"chiave": "osservazione", "label": "Scritture degli agenti sempre in osservazione", "tipo": "booleano",
         "default": False,
         "help": "le scritture degli agenti non si eseguono e si registrano come «cosa sarebbe successo»; "
                 "le letture continuano"},
        {"chiave": "eventi", "label": "Avvisa la fabbrica quando un'attività è assegnata a un agente",
         "tipo": "booleano", "default": True,
         "help": "si mandano solo il nome della vista, l'id del record e il nome dell'agente, mai testo"},
    ],
}
