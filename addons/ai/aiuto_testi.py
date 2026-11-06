"""«Scrivi con Ada»: aiuto a scrivere i campi di istruzioni (progetti, assistenti, attività pianificate).

Campo vuoto: Ada fa qualche domanda e scrive una bozza. Campo già scritto: lo migliora. In entrambi i casi controlla con
gli strumenti di sola lettura i nomi che cita (commesse, clienti, etichette, documenti), con i permessi dell'utente, e
non li inventa. La bozza va nel campo solo se l'utente la sceglie, e si salva solo con il form.

Il lavoro gira come un turno in una chat nascosta: costi nel tetto di spesa, testo mascherato come in chat."""
from .models import Conversazione, MessaggioChat, Turno

COMPITO = "aiuto"
SEPARATORE_NOTE = "NOTE:"
# strumenti esclusi anche se di sola lettura: creano qualcosa in chat o escono verso sistemi esterni
ESCLUSI = {"scrivi_documento", "modifica_documento", "grafico", "tabella", "cerca_web", "leggi_pagina", "ricorda"}

CAMPI = {
    "progetto": {
        "permesso": "ai.add_progettochat",
        "cosa": "le istruzioni di un progetto della chat: valgono per ogni chat del progetto e arrivano ad Ada a ogni messaggio",
        "domande": ["Su cosa lavori in questo progetto?", "Chi lo usa e per fare cosa?",
                    "Come vuoi le risposte? (tono, lunghezza, formato)", "Quali dati del gestionale o documenti servono? (facoltativo)",
                    "Cose da evitare (facoltativo)"],
        "struttura": "una riga sull'obiettivo; «Contesto» con i fatti stabili; «Come rispondere»; «Dati del gestionale» con i nomi "
                     "verificati; se serve, quando scrivere un documento accanto alla chat. Niente cose del momento.",
    },
    "assistente": {
        "permesso": "ai.change_assistente",
        "cosa": "le istruzioni di un assistente specializzato di Ada: definiscono il suo ruolo per tutte le persone che lo usano",
        "domande": ["Che cosa deve fare questo assistente e per chi?", "In quale app o reparto lavora?",
                    "Come deve rispondere?", "Che cosa non deve fare mai? (facoltativo)"],
        "struttura": "ruolo in una riga; compiti; come rispondere; dati e app da usare con i nomi verificati; limiti (cosa non fa e "
                     "quando passa a una persona). Scritto per chiunque lo userà, non per una persona sola.",
    },
    "pianificata": {
        "permesso": "ai.add_pianificata",
        "cosa": "l'istruzione di un'attività pianificata: Ada la esegue da sola a ogni scadenza, senza nessuno a cui chiedere chiarimenti",
        "domande": ["Che cosa deve fare Ada a ogni esecuzione?", "Quali dati deve guardare e con quali criteri?",
                    "Che cosa deve produrre e per chi? (riepilogo, avviso, documento)",
                    "Se non c'è niente da segnalare, che cosa fa? (facoltativo)"],
        "struttura": "un'istruzione che funzioni da sola: periodo relativo alla data di esecuzione (ieri, questa settimana), dati e "
                     "criteri precisi con i nomi verificati, formato del risultato, cosa fare se non c'è niente. Nessuna domanda all'utente.",
    },
}


def richiesta(chiave, testo_attuale, risposte):
    """Il messaggio per Ada: le risposte all'intervista (campo vuoto) o il testo da migliorare."""
    campo = CAMPI[chiave]
    regole = (f"Devi preparare {campo['cosa']}. Struttura consigliata: {campo['struttura']}\n"
              "Regole: italiano chiaro e diretto, frasi brevi, al massimo 300 parole. Prima di scrivere un nome del gestionale "
              "(commessa, cliente, progetto, etichetta, documento, app) controllalo con gli strumenti di sola lettura: usa solo nomi "
              "che trovi davvero; quelli che non trovi lasciali fuori e segnalali. Non inventare dati. Scrivi i nomi, senza link.\n"
              "Rispondi solo con il testo finale, pronto da incollare, senza premesse né commenti. Se hai cose da segnalare (nomi non "
              f"trovati, contraddizioni, parti da spostare nei file), aggiungile in fondo dopo una riga che contiene solo «{SEPARATORE_NOTE}».")
    if testo_attuale.strip():
        corpo = f"Migliora questo testo: accorcialo, togli ripetizioni e contraddizioni, completa ciò che manca.\n\n<testo>\n{testo_attuale.strip()}\n</testo>"
    else:
        righe = [f"- {d}\n  {str(risposte.get(str(i), '')).strip() or '(nessuna risposta)'}" for i, d in enumerate(campo["domande"])]
        corpo = "Scrivi il testo a partire da queste risposte:\n" + "\n".join(righe)
    return regole, corpo


def avvia(utente, azienda, chiave, testo_attuale="", risposte=None):
    from . import motore
    regole, corpo = richiesta(chiave, testo_attuale[:6000], {k: str(v)[:1500] for k, v in (risposte or {}).items()})
    conversazione = Conversazione.objects.create(utente=utente, titolo=f"Scrivi con Ada: {chiave}", nascosta=True)
    return motore.avvia(conversazione, corpo, utente, azienda, compito=COMPITO, nota=regole, web=False)


def esito(turno):
    """None se Ada sta ancora scrivendo; altrimenti {bozza, note} oppure {errore}."""
    if turno.stato == Turno.IN_CORSO:
        return None
    risposta = MessaggioChat.objects.filter(turno=turno, ruolo=MessaggioChat.ASSISTENTE).values_list("testo", flat=True).first() or ""
    if turno.stato != Turno.COMPLETATO or not risposta.strip():
        return {"errore": "Ada non è riuscita a scrivere la bozza: riprova tra poco."}
    bozza, _, note = risposta.partition(SEPARATORE_NOTE)
    return {"bozza": bozza.strip().strip("`").strip(), "note": note.strip()}


def filtra_strumenti(ammessi):
    """Per l'aiuto: solo letture del gestionale, niente che crei qualcosa o esca verso altri sistemi."""
    return {n: s for n, s in ammessi.items() if s.rischio == "lettura" and n not in ESCLUSI and not n.startswith("mcp")}
