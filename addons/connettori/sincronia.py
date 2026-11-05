"""Tenere allineati i contatti con il sistema esterno. Per ogni collegamento comanda uno solo dei due:

- comanda l'esterno: a intervalli si leggono i record cambiati e si copiano qui. Ciò che arriva non riparte verso fuori.
- comanda adabox: i contatti salvati qui si scrivono di là, uno per uno, in background.

Mai cancellazioni, in nessun verso, e un campo vuoto non cancella un valore: perdere un dato costa più di tenerne uno
vecchio. Se un'email porta a più contatti non si sceglie a caso: si salta e si segnala."""
import datetime
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core import lavori, sequenze

from . import eventi, riferimenti
from .models import CollegamentoEsterno
from .sistemi import hubspot, prova
from .sistemi.base import ErroreConnettore, ErroreTemporaneo

log = logging.getLogger("connettori.sincronia")
MARGINE = datetime.timedelta(minutes=5)       # i record cambiati compaiono nella ricerca con un po' di ritardo
MASSIMO_PAGINE = 50                           # il resto al prossimo giro: il cursore è già avanzato
LUNGHEZZE = {"nome": 200, "ruolo": 100, "indirizzo": 200, "citta": 100, "cap": 10, "telefono": 40, "cellulare": 40, "sito": 200, "email": 254}


def client(collegamento):
    if collegamento.sistema != CollegamentoEsterno.HUBSPOT:
        raise ErroreConnettore(f"Sistema non gestito: {collegamento.sistema}")
    if collegamento.modalita == CollegamentoEsterno.PROVA:
        return hubspot.HubSpot("prova", transport=prova.trasporto(collegamento))
    if not collegamento.token_cifrato:
        raise ErroreConnettore("Manca il token: inseriscilo nel collegamento.")
    return hubspot.HubSpot(collegamento.token())


def _esito(collegamento, testo, errore=False):
    CollegamentoEsterno.objects.filter(pk=collegamento.pk).update(ultimo_giro=timezone.now(), ultimo_esito=testo[:500], in_errore=errore)


def _applica(collegamento, record):
    """Un record esterno su un contatto: 'creato', 'aggiornato', 'uguale' o 'dubbio'."""
    from contatti.models import Contatto
    dati = {k: v[:LUNGHEZZE[k]] for k, v in hubspot.in_adabox(record).items()}
    if not dati.get("nome"):
        return "dubbio"
    azienda = collegamento.azienda
    contatto = riferimenti.trova(Contatto, azienda, collegamento.sistema, record["id"])
    if contatto is None and dati.get("email"):
        stessi = list(Contatto.objects.filter(azienda=azienda, email__iexact=dati["email"])[:2])
        if len(stessi) > 1:
            return "dubbio"
        if stessi:
            contatto = stessi[0]
    esito = "uguale"
    if contatto is None:
        contatto = Contatto.objects.create(azienda=azienda, codice=sequenze.prossimo("contatti.contatto", azienda), tipo=Contatto.PERSONA,
                                           cliente=True, **dati)
        esito = "creato"
    else:
        cambiati = [k for k, v in dati.items() if getattr(contatto, k) != v]
        if cambiati:
            for k in cambiati:
                setattr(contatto, k, dati[k])
            contatto.save(update_fields=cambiati)
            esito = "aggiornato"
    riferimenti.collega(contatto, collegamento.sistema, record["id"])
    return esito


def _istante(record):
    return parse_datetime((record.get("properties") or {}).get("lastmodifieddate") or "")


def importa(collegamento):
    """Legge i record cambiati dall'ultimo giro. Il cursore si salva a ogni pagina: un errore non fa ripartire da capo."""
    sistema = client(collegamento)
    conti = {"creato": 0, "aggiornato": 0, "uguale": 0, "dubbio": 0}
    da = collegamento.cursore - MARGINE if collegamento.cursore else datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
    dopo, cursore = None, collegamento.cursore
    for _ in range(MASSIMO_PAGINE):
        record, dopo = sistema.modificati_da(int(da.timestamp() * 1000), dopo)
        with eventi.senza_eventi(), transaction.atomic():
            for r in record:
                conti[_applica(collegamento, r)] += 1
                istante = _istante(r)
                if istante is not None and (cursore is None or istante > cursore):
                    cursore = istante
            CollegamentoEsterno.objects.filter(pk=collegamento.pk).update(cursore=cursore)
        if not dopo:
            break
    collegamento.cursore = cursore
    return conti


def giro(collegamento_id):
    """Un giro di un collegamento in cui comanda l'esterno. Rilancia gli errori temporanei: ci ripensa il lavoro."""
    collegamento = CollegamentoEsterno.objects.select_related("azienda").filter(pk=collegamento_id, attivo=True).first()
    if collegamento is None or collegamento.comanda != CollegamentoEsterno.ESTERNO:
        return None
    try:
        conti = importa(collegamento)
    except ErroreTemporaneo as e:
        _esito(collegamento, str(e), errore=True)
        raise
    except ErroreConnettore as e:
        _esito(collegamento, str(e), errore=True)
        return str(e)
    testo = f"Creati {conti['creato']}, aggiornati {conti['aggiornato']}, uguali {conti['uguale']}"
    if conti["dubbio"]:
        testo += f", saltati {conti['dubbio']} (senza nome o con più contatti per la stessa email)"
    _esito(collegamento, testo)
    return testo


giro.senza_transazione = True


def giro_di_tutti():
    """Dal cron: un lavoro per collegamento, così uno lento o in errore non ferma gli altri."""
    for pk in CollegamentoEsterno.objects.filter(attivo=True, comanda=CollegamentoEsterno.ESTERNO).values_list("pk", flat=True):
        lavori.accoda("connettori.sincronia.giro", collegamento_id=pk, max_tentativi=3)


def scrivi_fuori(collegamento_id, contatto_id):
    """Un contatto di adabox verso il sistema esterno. Solo persone con un'email: è la chiave con cui HubSpot le riconosce."""
    from contatti.models import Contatto
    collegamento = CollegamentoEsterno.objects.select_related("azienda").filter(pk=collegamento_id, attivo=True).first()
    contatto = Contatto.objects.filter(pk=contatto_id).first()
    if collegamento is None or contatto is None or contatto.azienda_id != collegamento.azienda_id or collegamento.comanda != CollegamentoEsterno.ADABOX:
        return None
    if contatto.tipo != Contatto.PERSONA or not contatto.email:
        return "saltato: serve una persona con un'email"
    sistema = client(collegamento)
    proprieta = hubspot.in_hubspot(contatto)
    try:
        id_est = riferimenti.id_esterno(contatto, collegamento.sistema) or sistema.trova_per_email(contatto.email)
        if id_est:
            sistema.aggiorna(id_est, proprieta)
        else:
            id_est = sistema.crea(proprieta)
    except ErroreTemporaneo as e:
        _esito(collegamento, str(e), errore=True)
        raise
    except ErroreConnettore as e:
        _esito(collegamento, f"{contatto}: {e}", errore=True)
        return str(e)
    with eventi.senza_eventi():
        riferimenti.collega(contatto, collegamento.sistema, id_est)
    _esito(collegamento, f"Scritto {contatto} su {collegamento.get_sistema_display()}")
    return "scritto"


scrivi_fuori.senza_transazione = True


def contatto_salvato(sender, instance, raw=False, **_):
    if raw or eventi.muto():
        return
    pk_azienda, pk = instance.azienda_id, instance.pk
    voci = list(CollegamentoEsterno.objects.filter(azienda_id=pk_azienda, attivo=True, comanda=CollegamentoEsterno.ADABOX).values_list("pk", flat=True))
    for collegamento_id in voci:
        transaction.on_commit(lambda c=collegamento_id: lavori.accoda("connettori.sincronia.scrivi_fuori", collegamento_id=c, contatto_id=pk, max_tentativi=5))
