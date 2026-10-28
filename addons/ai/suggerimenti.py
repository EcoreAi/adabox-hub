"""Domande suggerite sotto il composer: generali, o dell'app a cui la chat è limitata."""

GENERALI = [
    "Riassumi cosa c'è da fare oggi",
    "Quali scadenze ho questa settimana?",
    "Prepara un riepilogo per la riunione di lunedì",
    "Quali clienti non sento da più di un mese?",
]

PER_APP = {
    "todo": ["Quali attività sono scadute?", "Cosa devo fare oggi?", "Raggruppa le attività aperte per tag"],
    "contatti": ["Quali clienti sono di Cagliari?", "Trova i contatti senza email", "Elenca i fornitori attivi"],
    "calendario": ["Che appuntamenti ho domani?", "Trova un'ora libera giovedì", "Riepiloga gli eventi della settimana"],
    "crm": ["Quali opportunità chiudono questo mese?", "Qual è il valore della pipeline per fase?",
            "Quali trattative sono ferme da due settimane?"],
    "helpdesk": ["Quali ticket hanno lo SLA scaduto?", "Riassumi i ticket aperti più urgenti",
                 "Quali clienti hanno aperto più ticket?"],
    "progetti": ["Quali compiti sono in ritardo?", "A che punto è ogni progetto attivo?", "Chi ha più compiti aperti?"],
    "timesheet": ["Quante ore ho registrato questa settimana?", "Ore per progetto nel mese",
                  "Quali giorni mi mancano nel timesheet?"],
}


def per(ambito=""):
    return PER_APP.get(ambito, GENERALI)


def tutti():
    return {"": GENERALI, **PER_APP}
