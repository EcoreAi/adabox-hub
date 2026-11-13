"""«Fai dimenticare ad Ada»: un documento esce dall'assistente e dalle chat in cui è stato letto.

1. Il documento resta nell'archivio ma è escluso dall'indice (IndiceDocumento «escluso»): via i suoi frammenti, il
   riassunto e le note del chatter collegate; non si reindicizza più, nemmeno se cambia, finché non lo si riammette.
2. In ogni chat, di chiunque, in cui uno strumento l'ha restituito (cerca_conoscenza, leggi_documento, leggi_foglio),
   le letture del documento si tolgono dai risultati salvati, le risposte di quei turni diventano una nota e i
   riassunti automatici di quelle chat si cancellano: riprendendo la chat, il modello non lo rivede.
3. OblioDocumento registra chi, quando, perché e quanto è stato tolto, mai il testo.

Non si toccano: il file (si elimina dall'archivio come sempre), le memorie degli utenti, i documenti scritti accanto
alle chat (si contano, da controllare), ciò che è già uscito verso chat esterne, fornitori dei modelli o backup."""
import json

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models.functions import Cast
from django.urls import reverse
from django.utils import timezone

from .models import DocumentoChat, Evento, Frammento, IndiceDocumento, MessaggioChat, OblioDocumento, Turno

NOTA_RISULTATO = "Contenuto rimosso: il documento è stato fatto dimenticare all'assistente."
NOTA_RISPOSTA = ("_Risposta rimossa: usava un documento che è stato fatto dimenticare all'assistente "
                 "(Assistente AI → Documenti dimenticati)._")


def indirizzo(documento_id):
    return reverse("documenti:documenti_dettaglio", args=[documento_id])


def escluso(documento_id):
    return IndiceDocumento.objects.filter(documento_id=documento_id, stato=IndiceDocumento.ESCLUSO).exists()


def _ripulisci(contenuto, url):
    """(contenuto senza le letture del documento, letture tolte)."""
    try:
        dati = json.loads(contenuto)
    except (TypeError, ValueError):
        return NOTA_RISULTATO, 1
    if isinstance(dati, dict) and isinstance(dati.get("risultati"), list):
        restano = [r for r in dati["risultati"] if not str(r.get("url", "")).startswith(url)]
        tolte = len(dati["risultati"]) - len(restano)
        if tolte == 0 and url not in json.dumps(restano, ensure_ascii=False):
            return contenuto, 0
        dati = {**dati, "risultati": restano}
        if not restano:
            dati["nota"] = NOTA_RISULTATO
        testo = json.dumps(dati, ensure_ascii=False)
        if url in testo:                                     # il documento citato anche altrove nel risultato
            return json.dumps({"rimosso": NOTA_RISULTATO}, ensure_ascii=False), max(tolte, 1)
        return testo, tolte
    return json.dumps({"rimosso": NOTA_RISULTATO}, ensure_ascii=False), 1


@transaction.atomic
def dimentica(documento, utente, motivo=""):
    """Esclude il documento dall'assistente e lo toglie dalle chat. Restituisce la riga del registro."""
    ct = ContentType.objects.get_for_model(documento)
    url = indirizzo(documento.pk)
    IndiceDocumento.objects.update_or_create(documento_id=documento.pk, defaults={
        "azienda_id": documento.azienda_id, "nome": documento.nome[:200], "stato": IndiceDocumento.ESCLUSO,
        "messaggio": f"Fatto dimenticare all'assistente il {timezone.localtime():%d/%m/%Y}: non si legge più.",
        "frammenti": 0, "riassunto": "", "impronta_riassunto": "", "impronta": ""})
    frammenti = Frammento.objects.filter(content_type=ct, object_id=documento.pk).delete()[0]

    turni, conversazioni, letture = set(), set(), 0
    eventi = (Evento.objects.annotate(testo_json=Cast("dati", models.TextField()))
              .filter(tipo=Evento.STRUMENTO, testo_json__contains=url))
    for ev in eventi:
        risultati, toccato = [], False
        for r in ev.dati.get("risultati", []):
            if url in str(r.get("contenuto", "")):
                nuovo, tolte = _ripulisci(r["contenuto"], url)
                if tolte:
                    r, toccato, letture = {**r, "contenuto": nuovo}, True, letture + tolte
            risultati.append(r)
        if toccato:
            Evento.objects.filter(pk=ev.pk).update(dati={**ev.dati, "risultati": risultati})
            turni.add(ev.turno_id)
            conversazioni.add(ev.conversazione_id)
    turni.discard(None)

    risposte = 0
    for ev in Evento.objects.filter(turno_id__in=turni, tipo=Evento.ASSISTENTE):
        blocchi = ev.dati.get("blocchi", [])
        strumenti = [b for b in blocchi if b.get("tipo") == "strumento"]
        if len(strumenti) < len(blocchi):                    # testo e ragionamento del modello: via
            nuovi = strumenti or [{"tipo": "testo", "testo": NOTA_RISPOSTA}]
            Evento.objects.filter(pk=ev.pk).update(dati={**ev.dati, "blocchi": nuovi})
    risposte += MessaggioChat.objects.filter(turno_id__in=turni, ruolo=MessaggioChat.ASSISTENTE).update(testo=NOTA_RISPOSTA)
    Turno.objects.filter(pk__in=turni).update(testo=NOTA_RISPOSTA, provenienza={}, avanzamento=[])
    riassunti = Evento.objects.filter(conversazione_id__in=conversazioni, tipo=Evento.RIASSUNTO).delete()[0]
    documenti_chat = DocumentoChat.objects.filter(conversazione_id__in=conversazioni).count()
    return OblioDocumento.objects.create(
        azienda_id=documento.azienda_id, documento_id=documento.pk, nome=documento.nome[:200], utente=utente,
        motivo=(motivo or "")[:300], frammenti=frammenti, chat=len(conversazioni), risultati=letture,
        risposte=risposte, riassunti=riassunti, documenti_chat=documenti_chat)


def riammetti(documento, utente, motivo=""):
    """Il documento torna nell'indice (le chat ripulite restano ripulite)."""
    from . import conoscenza
    IndiceDocumento.objects.filter(documento_id=documento.pk).update(stato=IndiceDocumento.IN_CODA, messaggio="")
    registro = OblioDocumento.objects.create(azienda_id=documento.azienda_id, documento_id=documento.pk,
                                             nome=documento.nome[:200], utente=utente, motivo=(motivo or "")[:300],
                                             azione=OblioDocumento.RIAMMESSO)
    transaction.on_commit(lambda: conoscenza.accoda_documento(documento.pk))
    return registro
