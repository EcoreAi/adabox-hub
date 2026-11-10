"""Funzioni dell'assistente che il piano del cliente può comprendere o no (core.funzioni). Il catalogo, con nomi e
spiegazioni, è nel manifest; qui ciò che ognuna spegne nel codice. Le voci di menu e le impostazioni hanno la loro
«funzione» nel manifest, le viste ModelView.funzione, i template {% if funzioni.ai.<chiave> %}.

- piu_modelli: il selettore Veloce/Avanzato della chat; senza, risponde il modello scelto dagli amministratori
- ricerca_web: cerca_web, leggi_pagina, la ricerca approfondita
- memoria: lo strumento ricorda, la pagina Memoria e i ricordi nel prompt
- aree_di_lavoro: le aree con chat, istruzioni, file e record collegati
- pianificate: le attività pianificate (pagina, strumenti e esecuzione)
- conoscenza: la ricerca nei documenti, nelle note e nei record (cerca_conoscenza, leggi_documento, leggi_foglio)
- scritture: le modifiche ai dati proposte da Ada (crea, modifica, elimina, azioni, attività sui record)
- documenti: i documenti scritti accanto alla chat
- grafici: grafici e tabelle nella chat
- assistenti: gli assistenti delle app e gli esperti
- specialisti: previsioni e classificazioni dei servizi locali
- mcp: i sistemi esterni collegati con MCP
- voce: dettatura e lettura delle risposte"""
from core import funzioni

STRUMENTI = {
    "cerca_web": "ricerca_web", "leggi_pagina": "ricerca_web",
    "ricorda": "memoria",
    "crea_pianificata": "pianificate", "elenco_pianificate": "pianificate",
    "cerca_conoscenza": "conoscenza", "leggi_documento": "conoscenza", "leggi_foglio": "conoscenza",
    "crea_record": "scritture", "modifica_record": "scritture", "elimina_record": "scritture",
    "esegui_bottone": "scritture", "esegui_azione": "scritture", "pianifica_attivita": "scritture",
    "scrivi_documento": "documenti", "leggi_documento_chat": "documenti", "modifica_documento": "documenti",
    "grafico": "grafici", "tabella": "grafici",
    "chiedi_esperto": "assistenti", "elenco_esperti": "assistenti",
    "previsione": "specialisti", "classifica": "specialisti",
}


def attiva(chiave):
    return funzioni.attiva("ai", chiave)


def di_strumento(strumento):
    """La funzione a cui appartiene uno strumento: la sua, o quella della tabella qui sopra; "" = di base."""
    return strumento.funzione_licenza or STRUMENTI.get(strumento.nome, "")


def richiede(chiave):
    """Decoratore delle viste: 404 se la funzione non è compresa nella licenza."""
    from functools import wraps

    from django.http import Http404

    def decoratore(vista):
        @wraps(vista)
        def avvolta(request, *args, **kwargs):
            if not attiva(chiave):
                raise Http404("Funzione dell'assistente non compresa nella licenza.")
            return vista(request, *args, **kwargs)
        return avvolta
    return decoratore
