{
    "name": "Finanziamenti",
    "summary": "Mutui e finanziamenti con il piano delle rate (francese o italiano): rate da pagare, avvisi e debito residuo",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Contabilità",
    "depends": ["contatti"],
    "min_core": "1.0",
    "application": True,
    "icon": "finanziamenti/icon.svg",
    "riepilogo": "finanziamenti.riepilogo.voci",
    "menu": [
        {"label": "Finanziamenti", "url_name": "finanziamenti:finanziamenti_lista", "permission": "finanziamenti.view_finanziamento"},
        {"label": "Rate", "url_name": "finanziamenti:rate_lista", "permission": "finanziamenti.view_ratafinanziamento"},
    ],
    "groups": {
        "Finanziamenti / Utente": ["finanziamenti.view_finanziamento", "finanziamenti.view_ratafinanziamento",
                                   "finanziamenti.change_ratafinanziamento"],
        "Finanziamenti / Responsabile": ["finanziamenti.*"],
    },
}
