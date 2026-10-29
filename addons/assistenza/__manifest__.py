{
    "name": "Assistenza clienti",
    "summary": "Assistenza per progetto: portale clienti, widget di segnalazione, contratti SLA, ticket e compiti",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Servizi",
    "depends": ["helpdesk", "progetti"],
    "min_core": "1.0",
    "application": True,
    "icon": "assistenza/icon.svg",
    "menu": [
        {"label": "Supporto dei progetti", "url_name": "assistenza:supporto_lista",
         "permission": "assistenza.view_supporto"},
        {"label": "Contratti", "url_name": "assistenza:contratti_lista", "permission": "assistenza.view_contratto"},
        {"label": "Politiche SLA", "url_name": "assistenza:politiche_lista", "permission": "assistenza.change_politicasla"},
    ],
    "groups": {
        "Assistenza / Operatore": ["assistenza.view_supporto", "assistenza.view_contratto",
                                   "assistenza.view_politicasla", "assistenza.view_datiticket",
                                   "assistenza.change_datiticket"],
        "Assistenza / Responsabile": ["assistenza.*"],
    },
    "hooks": "assistenza.hooks",
}
