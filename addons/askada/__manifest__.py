{
    "name": "Chiedi ad Ada",
    "summary": "Su ogni pagina un'etichetta «Chiedi ad Ada»: l'assistente risponde su ciò che quella pagina mostra, KPI e grafici compresi",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Assistente",
    "depends": ["ai"],
    "min_core": "1.0",
    "application": True,
    "nav_label": "Chiedi ad Ada",
    "icon": "askada/icon.svg",
    "menu": [
        {"label": "Domande fatte", "url_name": "askada:domande_lista", "permission": "askada.view_domanda"},
    ],
    "groups": {
        "Chiedi ad Ada / Utente": ["askada.add_domanda"],
        "Chiedi ad Ada / Responsabile": ["askada.*"],
    },
    "hooks": "askada.hooks",
    "settings": [
        {"chiave": "caratteri_max", "label": "Testo della pagina passato all'assistente (caratteri)", "tipo": "intero", "default": 6000,
         "help": "Oltre questo limite il testo visibile della pagina viene tagliato; i dati strutturati (KPI, grafici) passano sempre"},
    ],
}
