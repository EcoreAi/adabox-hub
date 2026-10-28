{
    "name": "Acquisti",
    "summary": "Ordini ai fornitori con costi, IVA, stampa e invio; ricevimento in magazzino",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Acquisti",
    "depends": ["prodotti", "contatti"],
    "min_core": "1.0",
    "application": True,
    "icon": "acquisti/icon.svg",
    "dashboard": "acquisti.dashboard.kpi",
    "menu": [
        {"label": "Ordini ai fornitori", "url_name": "acquisti:ordini_lista", "permission": "acquisti.view_ordineacquisto"},
        {"label": "Analisi", "url_name": "acquisti:ordini_grafico", "permission": "acquisti.view_ordineacquisto"},
    ],
    "groups": {
        "Acquisti / Buyer": ["acquisti.view_ordineacquisto", "acquisti.add_ordineacquisto",
                             "acquisti.change_ordineacquisto", "acquisti.view_rigaacquisto", "acquisti.add_rigaacquisto",
                             "acquisti.change_rigaacquisto", "acquisti.delete_rigaacquisto"],
        "Acquisti / Responsabile": ["acquisti.*"],
    },
    "hooks": "acquisti.hooks",
    "sequences": [{"codice": "acquisti.ordine", "formato": "OA/{anno}/{numero:04d}", "azzera": "anno"}],
}
