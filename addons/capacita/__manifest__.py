{
    "name": "Capacità e consegne",
    "summary": "Quando finisce ogni compito e progetto: capacità delle persone, ferie e festività, dipendenze, carico, Gantt e simulazioni",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Servizi",
    "depends": ["timesheet"],
    "min_core": "1.0",
    "application": True,
    "icon": "capacita/icon.svg",
    "menu": [
        {"label": "Consegne", "url_name": "capacita:consegne", "permission": "capacita.view_capacita"},
        {"label": "Carico", "url_name": "capacita:carico", "permission": "capacita.view_capacita"},
        {"label": "Gantt", "url_name": "capacita:gantt", "permission": "capacita.view_capacita"},
        {"label": "E se…", "url_name": "capacita:simula", "permission": "capacita.view_capacita"},
        {"label": "Capacità delle persone", "url_name": "capacita:persone_lista", "permission": "capacita.view_capacita"},
    ],
    "groups": {
        "Capacità / Utente": ["capacita.view_capacita"],
        "Capacità / Responsabile": ["capacita.*"],
    },
}
