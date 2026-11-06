"""Ciò che accompagna ogni messaggio oltre al testo: la memoria dell'utente e le istruzioni del progetto."""
from .models import MemoriaUtente

MASSIMO_VOCI = 30
MASSIMO_CARATTERI = 3000


def nota_memoria(utente, azienda):
    if azienda is None:
        return ""
    righe, totale = [], 0
    for testo in MemoriaUtente.objects.filter(utente=utente, azienda=azienda).order_by("-pk").values_list("testo", flat=True)[:MASSIMO_VOCI]:
        totale += len(testo)
        if totale > MASSIMO_CARATTERI:
            break
        righe.append(f"- {testo}")
    return "L'utente ti ha chiesto di ricordare:\n" + "\n".join(righe) if righe else ""


def nota_progetto(conversazione):
    from . import allegati_chat
    progetto = conversazione.progetto
    if progetto is None:
        return ""
    righe = [f"Questa chat è nel progetto «{progetto.nome}»."]
    if progetto.istruzioni.strip():
        righe.append(f"Istruzioni dell'utente per il progetto:\n{progetto.istruzioni.strip()}")
    if file := allegati_chat.di_progetto(progetto):
        righe.append("File del progetto, da leggere con leggi_allegato se servono: " + ", ".join(f"«{a.nome}» (allegato n. {a.pk})" for a in file))
    righe += _nota_cartella(conversazione, progetto)
    from . import collegamenti
    if collegati := collegamenti.nota(conversazione.utente, progetto):
        righe.append(collegati)
    return "\n".join(righe)


def _nota_cartella(conversazione, progetto):
    """I documenti della cartella dei Documenti collegata, che l'utente vede: Ada li apre con leggi_documento."""
    from . import archivio
    if not progetto.cartella_documenti or not archivio.attivo():
        return []
    radice = archivio.cartella(conversazione.utente, progetto.azienda, progetto.cartella_documenti)
    if radice is None:
        return []
    documenti = archivio.documenti_in(conversazione.utente, progetto.azienda, radice)
    if not documenti:
        return [f"La cartella dei Documenti del progetto è «{radice.percorso()}»: per ora è vuota."]
    elenco = ", ".join(f"«{d.nome}» (documento n. {d.pk}{', in ' + d.cartella.nome if d.cartella_id != radice.pk else ''})"
                       for d in documenti[:archivio.MASSIMO_ELENCO])
    altri = f" e altri {len(documenti) - archivio.MASSIMO_ELENCO}" if len(documenti) > archivio.MASSIMO_ELENCO else ""
    return [f"Documenti della cartella del progetto «{radice.percorso()}» (app Documenti), da leggere con leggi_documento se servono: {elenco}{altri}."]
