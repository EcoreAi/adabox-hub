{
    "name": "SharePoint",
    "summary": "Le cartelle dei Documenti allineate con SharePoint (Microsoft 365): da SharePoint, verso SharePoint o nei due versi, con le sottocartelle",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Integrazioni",
    "depends": ["documenti"],
    "min_core": "1.0",
    "application": True,
    "icon": "sharepoint/icon.svg",
    "menu": [
        {"label": "Collegamenti", "url_name": "sharepoint:collegamenti_lista", "permission": "sharepoint.view_collegamentosharepoint"},
        {"label": "File allineati", "url_name": "sharepoint:file_lista", "permission": "sharepoint.view_filesharepoint"},
    ],
    "groups": {
        "SharePoint / Utente": ["sharepoint.view_collegamentosharepoint", "sharepoint.view_filesharepoint"],
        "SharePoint / Responsabile": ["sharepoint.*"],
    },
    "cron": [
        {"nome": "Allineamento con SharePoint", "funzione": "sharepoint.sincronia.giro_di_tutti", "ogni": "15m"},
    ],
}
