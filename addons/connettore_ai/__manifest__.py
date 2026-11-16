{
    "name": "Connettore AI",
    "summary": "adabox dentro Claude, ChatGPT, Gemini e Le Chat: ognuno interroga dalla chat che usa già i dati che può vedere, con il suo abbonamento",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Integrazioni",
    "depends": ["ai"],
    "min_core": "1.2",
    "application": True,
    "nav_label": "Chat AI esterne",
    "icon": "connettore_ai/icon.svg",
    "menu": [
        {"label": "Le mie chat AI", "url_name": "connettore_ai:mie", "permission": "connettore_ai.add_chatcollegata"},
        {"label": "Collegamenti", "url_name": "connettore_ai:collegamenti_lista", "permission": "connettore_ai.view_chatcollegata"},
        {"label": "Chiamate", "url_name": "connettore_ai:chiamate_lista", "permission": "connettore_ai.view_chiamata"},
        {"label": "Chat conosciute", "url_name": "connettore_ai:client_lista", "permission": "connettore_ai.view_clientoauth"},
        {"label": "Credenziali per Gemini Enterprise", "url_name": "connettore_ai:credenziali", "permission": "connettore_ai.add_clientoauth"},
    ],
    "menu_profilo": [
        {"label": "Le mie chat AI", "url_name": "connettore_ai:mie", "permission": "connettore_ai.add_chatcollegata", "icon": "users"},
    ],
    "groups": {
        "Connettore AI / Utente": ["connettore_ai.add_chatcollegata"],
        "Connettore AI / Responsabile": ["connettore_ai.*"],
    },
    "settings": [
        {"chiave": "attivo", "label": "Le persone di questa azienda possono collegare adabox alle chat AI esterne", "tipo": "booleano",
         "default": False, "per_azienda": True,
         "help": "Claude, ChatGPT, Gemini, Le Chat: i dati che la persona può vedere arrivano al fornitore della chat che usa. "
                 "Spento, nessuno si collega e i collegamenti esistenti smettono di rispondere"},
        {"chiave": "maschera", "label": "Proteggi i dati personali verso le chat esterne", "tipo": "booleano", "default": False,
         "per_azienda": True,
         "help": "nomi, codici fiscali, IBAN ed email escono come segnaposto ([FULLNAME_1]) e nella chat si leggono così; serve il "
                 "servizio di protezione dei dati personali dell'assistente. Se il servizio non risponde non esce nulla"},
        {"chiave": "client_locali", "label": "Ammetti i programmi sul computer dell'utente (Claude Code, Gemini CLI)", "tipo": "booleano",
         "default": False, "help": "il ritorno dell'autorizzazione va a http://127.0.0.1 o http://localhost, su qualsiasi porta"},
        {"chiave": "ritorni_extra", "label": "Altri indirizzi di ritorno ammessi", "tipo": "testo", "default": "",
         "help": "oltre a quelli di Claude, ChatGPT, Gemini e Le Chat: indirizzi https completi separati da spazi; con * in fondo vale "
                 "come inizio. Un indirizzo di ritorno riceve il codice che dà accesso ai dati: aggiungine solo di fornitori di cui ti fidi"},
    ],
    "cron": [
        {"nome": "Pulizia di codici e token scaduti delle chat AI esterne", "funzione": "connettore_ai.lavori.pulisci", "ogni": "1d"},
    ],
}
