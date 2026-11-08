"""Ciò che accompagna ogni messaggio oltre al testo: la memoria dell'utente e le istruzioni del progetto."""
from itertools import takewhile

from .models import MemoriaUtente

MASSIMO_VOCI = 30
MASSIMO_CARATTERI = 3000


INTESTAZIONE = "L'utente ti ha chiesto di ricordare:"
CANCELLATI = "L'utente ha cancellato tutti i ricordi: non usare quelli dei messaggi precedenti."


def nota_memoria_per(conversazione, utente, azienda):
    """La memoria nel contesto solo quando serve: al primo messaggio, quando cambia, o quando il messaggio che la
    conteneva è finito in un riassunto (il modello non la vede più). Ripeterla a ogni messaggio allunga la storia."""
    attuale = nota_memoria(utente, azienda)
    precedente = _ultima_memoria_vista(conversazione)
    if attuale:
        return "" if attuale == precedente else attuale
    return CANCELLATI if precedente and precedente != CANCELLATI else ""


def _ultima_memoria_vista(conversazione):
    """Il blocco della memoria nell'ultimo messaggio dell'utente che il modello vede ancora (dopo l'ultimo riassunto)."""
    if conversazione is None or conversazione.pk is None:
        return ""
    from .models import Evento
    eventi = conversazione.eventi.filter(tipo=Evento.UTENTE)
    riassunto = conversazione.eventi.filter(tipo=Evento.RIASSUNTO).order_by("-pk").first()
    if riassunto is not None:
        eventi = eventi.filter(pk__gt=riassunto.dati["fino_a"])
    for dati in eventi.order_by("-pk").values_list("dati", flat=True)[:200]:
        contesto = (dati or {}).get("testo", "").split("</contesto>", 1)[0]
        if CANCELLATI in contesto:
            return CANCELLATI
        if INTESTAZIONE in contesto:
            blocco = contesto[contesto.index(INTESTAZIONE):].split("\n")
            return "\n".join([blocco[0], *takewhile(lambda r: r.startswith("- "), blocco[1:])])
    return ""


def nota_memoria(utente, azienda):
    if azienda is None:
        return ""
    righe, totale = [], 0
    for testo in MemoriaUtente.objects.filter(utente=utente, azienda=azienda).order_by("-pk").values_list("testo", flat=True)[:MASSIMO_VOCI]:
        totale += len(testo)
        if totale > MASSIMO_CARATTERI:
            break
        righe.append(f"- {testo}")
    return INTESTAZIONE + "\n" + "\n".join(righe) if righe else ""


def nota_progetto(conversazione):
    from . import allegati_chat
    progetto = conversazione.progetto
    if progetto is None:
        return ""
    righe = [f"Questa chat è nell'area di lavoro «{progetto.nome}» (area n. {progetto.pk})."]
    if progetto.istruzioni.strip():
        righe.append(f"Istruzioni per l'area di lavoro:\n{progetto.istruzioni.strip()}")
    if progetto.app_collegate:
        from core.registry import modules
        nomi = {s: m.name for s, m in modules.manifests_attivi().items()}
        app = [f"{nomi.get(s, s)} ({s})" for s in progetto.app_collegate if s in nomi]
        if app:
            righe.append("L'area lavora con queste app: " + ", ".join(app) + ". Usa di preferenza le loro viste.")
    if file := allegati_chat.di_progetto(progetto):
        righe.append("File dell'area di lavoro, da leggere con leggi_allegato se servono: " + ", ".join(f"«{a.nome}» (allegato n. {a.pk})" for a in file))
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
        return [f"La cartella dei Documenti dell'area di lavoro è «{radice.percorso()}»: per ora è vuota."]
    elenco = ", ".join(f"«{d.nome}» (documento n. {d.pk}{', in ' + d.cartella.nome if d.cartella_id != radice.pk else ''})"
                       for d in documenti[:archivio.MASSIMO_ELENCO])
    altri = f" e altri {len(documenti) - archivio.MASSIMO_ELENCO}" if len(documenti) > archivio.MASSIMO_ELENCO else ""
    return [f"Documenti della cartella dell'area di lavoro «{radice.percorso()}» (app Documenti), da leggere con leggi_documento se servono: {elenco}{altri}."]
