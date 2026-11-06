{
    "name": "Portale clienti",
    "summary": "L'area riservata dei clienti: preventivi, ordini, fatture, richieste di assistenza e progetti, ognuna dalla sua app",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Vendite e clienti",
    "depends": ["contatti"],
    "min_core": "1.0",
    "application": True,
    "icon": "portale/icon.svg",
    "menu": [
        {"label": "Accessi al portale", "url_name": "portale:accessi_lista", "permission": "portale.view_accessoportale"},
    ],
    "groups": {
        "Portale / Gestore": ["portale.*"],
    },
    "email": [
        {"codice": "portale.invito", "nome": "Invito al portale clienti", "gruppo": "Portale clienti",
         "oggetto": "Il tuo accesso al portale clienti di {{ marchio }}",
         "corpo": "Ciao {{ nome }},\n\nnel portale clienti trovi i documenti e le richieste di {{ cliente }}.\n\nScegli la tua password:\n{{ link_password }}\n\nPoi entri da {{ link_accesso }} con il nome utente {{ nome_utente }}.\n",
         "campi": {"nome": ["Nome della persona", "Anna"], "cliente": ["Il cliente", "Rossi Srl"],
                    "link_password": ["Link per scegliere la password", "https://hub.example.it/accounts/reset/abc/"],
                    "link_accesso": ["Pagina di accesso", "https://hub.example.it/accounts/login/"], "nome_utente": ["Nome utente", "anna@rossi.it"]},
         "obbligatori": ["link_password"]},
    ],
}
