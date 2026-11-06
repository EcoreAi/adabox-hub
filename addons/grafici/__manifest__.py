{
    "name": "Analisi",
    "summary": "Pagine di grafici e KPI, per utente e per app: ogni grafico è una query salvata che si aggiorna, cambia tipo e si spiega con Ada",
    "version": "1.2.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Direzione",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "nav_label": "Analisi",
    "icon": "grafici/icon.svg",
    "menu": [
        {"label": "Pagine", "url_name": "grafici:pagine", "permission": "grafici.view_pagina"},
        {"label": "Grafici salvati", "url_name": "grafici:salvati_lista", "permission": "grafici.view_grafico"},
    ],
    "groups": {
        "Analisi / Utente": ["grafici.view_pagina", "grafici.add_pagina", "grafici.change_pagina", "grafici.delete_pagina",
                             "grafici.view_grafico", "grafici.add_grafico", "grafici.change_grafico", "grafici.delete_grafico"],
        "Analisi / Responsabile": ["grafici.*"],
    },
    "hooks": "grafici.hooks",
    "ai": "grafici.ai",
    "cron": [{"nome": "Ricalcolo dei grafici di Analisi", "funzione": "grafici.lavori.aggiorna_scaduti", "ogni": "15m"}],
    "settings": [
        {"chiave": "cache_minuti", "label": "Dati dei grafici ricalcolati dopo (minuti)", "tipo": "intero", "default": 15,
         "help": "Aprendo una pagina, i grafici più vecchi di così si ricalcolano; «Aggiorna ora» ricalcola subito"},
    ],
}
