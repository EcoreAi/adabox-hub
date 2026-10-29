{
    "name": "GitHub",
    "summary": "Repository dei progetti: commit e pull request collegati ai compiti, chiusura al merge, rilasci dai tag",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Servizi",
    "depends": ["progetti"],
    "min_core": "1.0",
    "application": False,
    "icon": "github/icon.svg",
    "menu": [
        {"label": "Repository GitHub", "url_name": "github:repository_lista", "permission": "github.view_repository"},
    ],
    "groups": {
        "GitHub / Utente": ["github.view_repository", "github.view_collegamento"],
        "GitHub / Responsabile": ["github.*"],
    },
    "settings": [
        {"chiave": "prefisso", "label": "Prefisso dei riferimenti ai compiti nei commit e nelle pull request",
         "tipo": "testo", "default": "ADA",
         "help": "con ADA, «ADA-123» nel messaggio di commit, nel titolo o nel ramo collega il compito 123"},
    ],
}
