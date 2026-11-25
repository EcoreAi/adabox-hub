{
    "name": "Previsioni",
    "summary": "Previsioni di vendite e magazzino sui dati dell'azienda, con Timestral",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Direzione",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "previsioni/icon.svg",
    "ai": "previsioni.ai",
    "menu": [
        {"label": "Articoli in esaurimento", "url_name": "previsioni:esaurimenti_lista",
         "permission": "previsioni.view_previsionearticolo"},
    ],
    "groups": {
        "Previsioni / Utente": ["previsioni.view_previsionearticolo", "previsioni.view_previsionepronta"],
        "Previsioni / Responsabile": ["previsioni.*"],
    },
    "settings": [
        {"chiave": "url_servizio", "label": "URL del servizio di previsione", "tipo": "testo", "default": "",
         "help": "es. http://adabox-forecast-1:8080 o un servizio remoto; vuoto = previsioni spente"},
    ],
    "cron": [{"nome": "Previsioni della notte", "funzione": "previsioni.calcolo.notturno", "ogni": "1d", "alle": "02:00"}],
}
