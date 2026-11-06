"""Ponte verso l'app Documenti, se è installata: cartella collegata a un progetto, salvataggio di documenti, grafici e
tabelle nell'archivio, caricamento di una cartella intera. Tutto con i permessi di chi lo fa: Documenti decide chi
vede e chi scrive (gruppi, spazi di lavoro, quote, versioni). Senza Documenti queste funzioni semplicemente non ci sono."""
from django.conf import settings
from django.core.files.base import ContentFile

MASSIMO_ELENCO = 40
MASSIMI_FILE_CARICAMENTO = 200


class ArchivioNonDisponibile(Exception):
    pass


def attivo():
    return "documenti" in settings.ADDONS_ATTIVI


def cartelle(utente, azienda, scrittura=False):
    """[(cartella, percorso)] che l'utente vede (o in cui scrive), in ordine di percorso."""
    if not attivo() or azienda is None:
        return []
    from documenti import accesso
    voci = accesso.scrivibili(utente, azienda) if scrittura else accesso.visibili(utente, azienda)
    return sorted(((c, c.percorso()) for c in voci), key=lambda v: v[1].lower())


def cartella(utente, azienda, pk, scrittura=False):
    """La cartella se l'utente la vede (o ci scrive), altrimenti None."""
    if not pk:
        return None
    return next((c for c, _ in cartelle(utente, azienda, scrittura) if c.pk == int(pk)), None)


def _albero(radice, visibili):
    """La cartella e le sue sottocartelle, tra quelle visibili."""
    figli = {}
    for c in visibili:
        figli.setdefault(c.padre_id, []).append(c)
    uscita, coda = [], [radice]
    while coda:
        c = coda.pop()
        uscita.append(c)
        coda += figli.get(c.pk, [])
    return uscita


def documenti_in(utente, azienda, radice):
    """I documenti della cartella e delle sottocartelle che l'utente vede, i più recenti prima."""
    if radice is None:
        return []
    from documenti import accesso
    from documenti.models import Documento
    visibili = accesso.visibili(utente, azienda)
    if radice.pk not in {c.pk for c in visibili}:
        return []
    return list(Documento.objects.filter(cartella__in=_albero(radice, visibili), cestinato_il__isnull=True)
                .select_related("cartella").order_by("-modificato"))


def salva(utente, azienda, cartella_pk, nome, contenuto):
    """Archivia `contenuto` (byte) come `nome` nella cartella: se c'è già un documento con quel nome diventa la sua
    versione nuova. Restituisce il documento."""
    if not attivo():
        raise ArchivioNonDisponibile("L'app Documenti non è installata.")
    destinazione = cartella(utente, azienda, cartella_pk, scrittura=True)
    if destinazione is None:
        raise ArchivioNonDisponibile("Non puoi scrivere in questa cartella.")
    from documenti import servizi
    return servizi.carica(destinazione, ContentFile(contenuto, name=nome), utente)


def carica_cartella(utente, azienda, radice, file, percorsi):
    """Carica una cartella scelta dal PC: le sottocartelle si ricreano dentro `radice` (ereditano i suoi permessi).
    (documenti caricati, errori)."""
    from core.allegati import AllegatoNonValido
    from documenti import accesso, servizi
    from documenti.models import Cartella
    if radice is None or not accesso.puo_scrivere(utente, radice):
        raise ArchivioNonDisponibile("Non puoi scrivere in questa cartella.")
    caricati, errori, create = [], [], {}
    for f, percorso in list(zip(file, list(percorsi) + [""] * len(file)))[:MASSIMI_FILE_CARICAMENTO]:
        parti = [p for p in str(percorso or "").replace("\\", "/").split("/") if p and p not in (".", "..")][1:-1]
        dove = radice
        for nome in parti:                               # la prima parte è la cartella scelta, l'ultima il file
            chiave = (dove.pk, nome[:120])
            if chiave not in create:
                create[chiave] = (Cartella.objects.filter(azienda=azienda, padre=dove, nome=nome[:120]).first()
                                  or Cartella.objects.create(azienda=azienda, padre=dove, nome=nome[:120]))
            dove = create[chiave]
        try:
            caricati.append(servizi.carica(dove, f, utente))
        except AllegatoNonValido as e:
            errori.append(str(e))
    if len(file) > MASSIMI_FILE_CARICAMENTO:
        errori.append(f"Caricati i primi {MASSIMI_FILE_CARICAMENTO} file: per cartelle più grandi usa l'archivio zip dei Documenti.")
    return caricati, errori


def url_cartella(c):
    from django.urls import reverse
    return f"{reverse('documenti:archivio')}?cartella={c.pk}"


def url_documento(d):
    from django.urls import reverse
    return reverse("documenti:documenti_dettaglio", args=[d.pk])
