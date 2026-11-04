{
    "name": "Rivendita",
    "summary": "Il portale di chi vende adabox: clienti e istanze, piani, moduli pubblicati, licenze firmate e richieste dal catalogo",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Direzione",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "nav_label": "Rivendita",
    "icon": "rivendita/icon.svg",
    "menu": [
        {"label": "Istanze", "url_name": "rivendita:istanze_lista", "permission": "rivendita.view_istanza"},
        {"label": "Richieste", "url_name": "rivendita:richieste_lista", "permission": "rivendita.view_richiesta"},
        {"label": "Piani", "url_name": "rivendita:piani_lista", "permission": "rivendita.view_piano"},
        {"label": "Moduli in vendita", "url_name": "rivendita:moduli_lista", "permission": "rivendita.view_modulovendibile"},
        {"label": "Pacchetti", "url_name": "rivendita:pacchetti_lista", "permission": "rivendita.view_pacchetto"},
        {"label": "Carica un pacchetto", "url_name": "rivendita:carica", "permission": "rivendita.change_pacchetto"},
    ],
    "groups": {
        "Rivendita / Responsabile": ["rivendita.*"],
    },
    "dashboard": "rivendita.dashboard.dati",
}
