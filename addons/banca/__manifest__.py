{
    "name": "Banca",
    "summary": "Estratti conto importati e abbinati a fatture e fornitori: gli incassi si registrano con un clic, senza contabilità",
    "version": "1.0.1",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Contabilità",
    "depends": ["sdi"],
    "min_core": "1.0",
    "riepilogo": "banca.riepilogo.voci",
    "application": True,
    "icon": "banca/icon.svg",
    "dashboard": "banca.dashboard.kpi",
    "menu": [
        {"label": "Da abbinare", "url_name": "banca:riconcilia", "permission": "banca.view_movimentobanca"},
        {"label": "Movimenti", "url_name": "banca:movimenti_lista", "permission": "banca.view_movimentobanca"},
        {"label": "Importa estratto", "url_name": "banca:importa", "permission": "banca.add_importazione"},
        {"label": "Conti", "url_name": "banca:conti_lista", "permission": "banca.view_conto"},
    ],
    "groups": {
        "Banca / Utente": ["banca.view_conto", "banca.view_movimentobanca", "banca.view_abbinamento", "banca.view_importazione"],
        "Banca / Responsabile": ["banca.*", "fatturazione.view_scadenza", "fatturazione.add_incasso", "fatturazione.delete_incasso",
                                 "sdi.view_scadenzapassiva", "sdi.change_scadenzapassiva"],
    },
}
