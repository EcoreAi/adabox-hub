{
    "name": "Distinte di pagamento",
    "summary": "Bonifici SEPA ai fornitori, addebiti SDD e RiBa ai clienti dalle scadenze aperte, con file per la banca ed esiti",
    "version": "1.0.1",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Contabilità",
    "depends": ["banca"],
    "min_core": "1.0",
    "application": True,
    "icon": "distinte/icon.svg",
    "menu": [
        {"label": "Distinte", "url_name": "distinte:distinte_lista", "permission": "distinte.view_distinta"},
        {"label": "Nuova distinta", "url_name": "distinte:nuova", "permission": "distinte.add_distinta"},
        {"label": "Mandati SDD", "url_name": "distinte:mandati_lista", "permission": "distinte.view_mandato"},
    ],
    "groups": {
        "Distinte / Utente": ["distinte.view_distinta", "distinte.view_vocedistinta", "distinte.view_mandato",
                              "distinte.view_coordinatebancarie", "distinte.view_configconto"],
        "Distinte / Responsabile": ["distinte.*", "fatturazione.view_scadenza", "fatturazione.add_incasso",
                                    "fatturazione.delete_incasso", "sdi.view_scadenzapassiva", "sdi.change_scadenzapassiva"],
    },
}
