{
    "name": "Agentic Workforce",
    "summary": "Agenti AI in affitto che lavorano nel gestionale, con Agate come garante delle loro azioni",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": ["ai"],
    "min_core": "1.0",
    "application": False,
    "icon": "awf/icon.svg",
    "menu_profilo": [
        {"label": "Agenti AI", "url_name": "awf:indice", "permission": "awf.change_collegamento", "icon": "users"},
    ],
    "groups": {
        "AWF / Amministratore": ["awf.*"],
    },
    "hooks": "awf.hooks",
    "ai": "awf.ai",
    "cron": [
        {"nome": "Battito verso la fabbrica degli agenti", "funzione": "awf.lavori.battito", "ogni": "15m"},
        {"nome": "Stato delle richieste di agenti", "funzione": "awf.lavori.richieste", "ogni": "5m"},
    ],
    "settings": [
        {"chiave": "osservazione", "label": "Agenti sempre come nel periodo di prova", "tipo": "booleano",
         "default": False,
         "help": "le modifiche degli agenti non si eseguono e si registrano come «cosa sarebbe successo»; "
                 "le letture continuano"},
        {"chiave": "eventi", "label": "Avvisa la fabbrica quando un'attività è assegnata a un agente",
         "tipo": "booleano", "default": True,
         "help": "si mandano solo il nome della vista, l'id del record e il nome dell'agente, mai testo"},
    ],
}
