{
    "name": "Wiki",
    "summary": "La wiki interna: spazi con i loro permessi, pagine ad albero in markdown, versioni, collegamenti tra pagine e ai record",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Collaborazione",
    "depends": [],
    "min_core": "1.0",
    "application": True,
    "icon": "wiki/icon.svg",
    "menu": [
        {"label": "Pagine", "url_name": "wiki:pagine_lista", "permission": "wiki.view_paginawiki"},
        {"label": "Spazi", "url_name": "wiki:spazi_lista", "permission": "wiki.view_spaziowiki"},
    ],
    "groups": {
        "Wiki / Utente": ["wiki.view_spaziowiki", "wiki.view_paginawiki", "wiki.add_paginawiki", "wiki.change_paginawiki",
                          "wiki.view_versionepagina"],
        "Wiki / Responsabile": ["wiki.*"],
    },
}
