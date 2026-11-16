{
    "name": "Posta e calendario",
    "summary": "La casella e il calendario di Google o Microsoft di ogni utente: le email con i clienti nel loro storico, gli appuntamenti nei due versi e un feed del calendario da abbonare",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Integrazioni",
    "depends": ["contatti", "calendario"],
    "min_core": "1.0",
    "application": False,
    "icon": "posta/icon.svg",
    "menu_profilo": [
        {"label": "Posta e calendario", "url_name": "posta:caselle", "permission": "posta.add_casella", "icon": "inbox"},
        {"label": "Servizi di posta", "url_name": "posta:servizi_lista", "permission": "posta.change_serviziooauth", "icon": "tool"},
        {"label": "Caselle degli utenti", "url_name": "posta:caselle_utenti_lista", "permission": "posta.view_casella", "icon": "users"},
    ],
    "groups": {
        "Posta e calendario / Utente": ["posta.add_casella"],       # la propria casella, dalla propria pagina
        "Posta e calendario / Amministratore": ["posta.*"],
    },
    "hooks": "posta.hooks",
    "cron": [
        {"nome": "Posta e calendari degli utenti", "funzione": "posta.sincronia.giro_di_tutte", "ogni": "10m"},
    ],
}
