{
    "name": "Impostazioni fiscali",
    "summary": "Aliquote IVA con natura e termini di pagamento, comuni a vendite, acquisti e fatture",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Contabilità",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "fiscale/icon.svg",
    "menu": [
        {"label": "Aliquote IVA", "url_name": "fiscale:aliquote_lista", "permission": "fiscale.view_aliquotaiva"},
        {"label": "Termini di pagamento", "url_name": "fiscale:termini_lista", "permission": "fiscale.view_terminepagamento"},
    ],
    "groups": {
        "Fiscale / Lettura": ["fiscale.view_aliquotaiva", "fiscale.view_terminepagamento"],
        "Fiscale / Responsabile": ["fiscale.*"],
    },
    "data": ["data/iniziali.json"],
    "hooks": "fiscale.hooks",
}
