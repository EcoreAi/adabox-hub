"""I dati che si possono cancellare dopo un tempo: li dichiarano i moduli (anche in ready()), l'amministratore sceglie i
giorni. Solo ciò che è registrato qui può avere una regola: niente cancellazioni su modelli scelti a caso."""
from django.apps import apps

_TIPI = {}       # chiave -> {"modello", "campo_data", "etichetta", "filtro"}


def registra(chiave, modello, campo_data, etichetta, filtro=None, giorni_consigliati=None):
    """`modello` «app.Modello»; `filtro` facoltativo: funzione(queryset) → queryset con solo i record cancellabili
    (es. le email già abbinate)."""
    _TIPI[chiave] = {"modello": modello, "campo_data": campo_data, "etichetta": etichetta, "filtro": filtro,
                     "giorni": giorni_consigliati}


def tipi():
    """{chiave: voce} dei tipi con il modulo installato."""
    risultato = {}
    for chiave, voce in _TIPI.items():
        app, _, nome = voce["modello"].partition(".")
        if apps.is_installed(app) or app == "core":
            risultato[chiave] = voce
    return risultato


def etichetta(chiave):
    return _TIPI.get(chiave, {}).get("etichetta", chiave)


def registra_predefiniti():
    registra("core.email_ricevute", "core.EmailRicevuta", "ricevuta", "Email ricevute nella casella delle risposte", giorni_consigliati=365)
    registra("core.lavori", "core.Lavoro", "creato", "Lavori in background conclusi",
             filtro=lambda qs: qs.exclude(finito=None), giorni_consigliati=90)
    registra("core.registro", "core.RegistroModifica", "creato", "Registro delle modifiche", giorni_consigliati=3650)
    registra("privacy.richieste", "privacy.RichiestaInteressato", "ricevuta_il", "Richieste degli interessati evase",
             filtro=lambda qs: qs.exclude(evasa_il=None), giorni_consigliati=1825)
    if apps.is_installed("ai"):
        registra("ai.conversazioni", "ai.Conversazione", "aggiornata", "Chat con l'assistente", giorni_consigliati=730)
