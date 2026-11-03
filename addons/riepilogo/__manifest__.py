{
    "name": "Riepilogo giornaliero",
    "summary": "All'accesso, che cosa è successo mentre non c'eri e che cosa aspetta te oggi: vendite, messaggi, appuntamenti, scadenze, approvazioni",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Produttività",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "nav_label": "Riepilogo",
    "icon": "riepilogo/icon.svg",
    "menu": [
        {"label": "Il mio riepilogo", "url_name": "riepilogo:pagina", "permission": "riepilogo.view_preferenza"},
    ],
    "groups": {
        "Riepilogo / Utente": ["riepilogo.view_preferenza"],
    },
    "hooks": "riepilogo.hooks",
    "settings": [
        {"chiave": "giorni_massimi", "label": "Guarda indietro al massimo (giorni)", "tipo": "intero", "default": 30,
         "help": "Dopo un'assenza più lunga il riepilogo parte da qui, non dall'ultimo accesso"},
    ],
}
