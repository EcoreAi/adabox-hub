{
    "name": "Reception",
    "summary": "Registro dei visitatori: entrata e uscita dal tablet all'ingresso, avviso a chi li riceve, presenti per l'evacuazione",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Risorse umane",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "reception/icon.svg",
    "menu": [
        {"label": "Chiosco", "url_name": "reception:chiosco", "permission": "reception.add_visita"},
        {"label": "Presenti ora", "url_name": "reception:presenti", "permission": "reception.view_visita"},
        {"label": "Visite", "url_name": "reception:visite_lista", "permission": "reception.view_visita"},
    ],
    "groups": {
        "Reception / Chiosco": ["reception.add_visita", "reception.view_visita"],
        "Reception / Responsabile": ["reception.*"],
    },
    "settings": [
        {"chiave": "informativa", "label": "Informativa privacy per i visitatori", "tipo": "testo", "per_azienda": True,
         "default": "I dati che inserisci (nome, azienda, orari) servono solo a registrare la visita e a garantire la "
                    "sicurezza delle persone presenti; li conserviamo per il tempo indicato e poi li cancelliamo.",
         "help": "Il testo che il visitatore accetta sul tablet prima di entrare"},
        {"chiave": "giorni_conservazione", "label": "Giorni di conservazione delle visite", "tipo": "intero", "default": 365,
         "per_azienda": True, "help": "Dopo, le visite si cancellano da sole"},
    ],
    "cron": [
        {"nome": "Cancella le visite vecchie", "funzione": "reception.servizi.cancella_vecchie", "ogni": "1d", "alle": "03:30"},
    ],
}
