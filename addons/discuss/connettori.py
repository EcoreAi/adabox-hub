"""WhatsApp e Telegram: i clienti scrivono dalla loro app e la conversazione arriva nelle Comunicazioni.

Un connettore sa solo tradurre: legge il formato della piattaforma, controlla che il messaggio venga davvero da lì e
prepara la richiesta di invio. Tutto il resto è lo stesso della chat sul sito (AI, passaggio a una persona, operatori).
Una connessione di prova (`sandbox`) percorre lo stesso codice, firme comprese, e non esce mai in rete.

Regole delle piattaforme che valgono anche qui:
- WhatsApp: fuori dalle 24 ore dall'ultimo messaggio del cliente si possono mandare solo modelli approvati da Meta.
- Telegram: un bot non può scrivere per primo, e risponde solo in chat private."""
import datetime
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

import httpx2 as httpx
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core import lavori, parametri

from . import assistente_sito, eventi, livechat
from .models import Connessione, ConversazioneEsterna, EventoEsterno, Messaggio, Sportello

log = logging.getLogger("discuss.connettori")
FINESTRA_WHATSAPP = datetime.timedelta(hours=24)
MASSIMO_CORPO = 512_000
MASSIMO_TESTO = 4096                    # lo stesso limite per entrambe le piattaforme
CHIEDE_PERSONA = {"/persona", "/operatore", "persona", "operatore"}
GIORNI_EVENTI = 7


class ErroreConsegna(Exception):
    """`temporaneo`: vale la pena riprovare (troppe richieste, servizio giù)."""

    def __init__(self, testo, temporaneo=False):
        super().__init__(testo)
        self.temporaneo = temporaneo


@dataclass
class Entrata:
    id: str
    mittente: str
    nome: str
    testo: str = ""
    tipo: str = "text"


@dataclass
class Stato:
    id: str
    stato: str
    errore: str = ""


# --- traduzioni ---

class WhatsApp:
    NOME = "WhatsApp"

    @staticmethod
    def autentica(c, corpo, intestazioni):
        firma = intestazioni.get("X-Hub-Signature-256", "")
        attesa = "sha256=" + hmac.new(c.segreto().encode(), corpo, hashlib.sha256).hexdigest()
        return bool(c.segreto()) and hmac.compare_digest(firma, attesa)

    @staticmethod
    def leggi(c, dati):
        entrate, stati = [], []
        for entry in dati.get("entry") or []:
            for change in entry.get("changes") or []:
                valore = change.get("value") or {}
                meta = valore.get("metadata") or {}
                if c.id_numero and meta.get("phone_number_id") and str(meta["phone_number_id"]) != c.id_numero:
                    continue                       # un altro numero dello stesso account
                nomi = {x.get("wa_id"): (x.get("profile") or {}).get("name", "") for x in valore.get("contacts") or []}
                for m in valore.get("messages") or []:
                    entrate.append(Entrata(id=str(m.get("id")), mittente=str(m.get("from")), nome=nomi.get(m.get("from"), ""),
                                           tipo=m.get("type", ""), testo=(m.get("text") or {}).get("body", "") if m.get("type") == "text" else ""))
                for s in valore.get("statuses") or []:
                    errori = s.get("errors") or []
                    stati.append(Stato(id=str(s.get("id")), stato=s.get("status", ""),
                                       errore=(errori[0].get("title") or str(errori[0].get("code"))) if errori else ""))
        return entrate, stati

    @staticmethod
    def richiesta(c, destinatario, testo):
        versione = parametri.leggi("discuss.versione_graph") or "v24.0"
        return (f"https://graph.facebook.com/{versione}/{c.id_numero}/messages", {"Authorization": f"Bearer {c.token()}"},
                {"messaging_product": "whatsapp", "recipient_type": "individual", "to": destinatario, "type": "text",
                 "text": {"preview_url": False, "body": testo}})

    @staticmethod
    def risposta(stato, dati):
        if 200 <= stato < 300:
            return str(((dati.get("messages") or [{}])[0]).get("id", ""))
        errore = dati.get("error") or {}
        raise ErroreConsegna(errore.get("message") or f"Errore {stato}", temporaneo=stato == 429 or stato >= 500)


class Telegram:
    NOME = "Telegram"

    @staticmethod
    def autentica(c, corpo, intestazioni):
        return bool(c.segreto()) and hmac.compare_digest(intestazioni.get("X-Telegram-Bot-Api-Secret-Token", ""), c.segreto())

    @staticmethod
    def leggi(c, dati):
        m = dati.get("message")
        if not isinstance(m, dict) or (m.get("chat") or {}).get("type") != "private":
            return [], []                          # gruppi e canali: il bot risponde solo in privato
        autore = m.get("from") or {}
        if autore.get("is_bot"):
            return [], []
        nome = " ".join(x for x in (autore.get("first_name"), autore.get("last_name")) if x) or autore.get("username", "")
        testo = m.get("text", "")
        return [Entrata(id=str(dati.get("update_id")), mittente=str(m["chat"]["id"]), nome=nome, testo=testo, tipo="text" if testo else "altro")], []

    @staticmethod
    def richiesta(c, destinatario, testo):
        return f"https://api.telegram.org/bot{c.token()}/sendMessage", {}, {"chat_id": destinatario, "text": testo}

    @staticmethod
    def risposta(stato, dati):
        if dati.get("ok"):
            return str((dati.get("result") or {}).get("message_id", ""))
        raise ErroreConsegna(dati.get("description") or f"Errore {stato}", temporaneo=stato == 429 or stato >= 500)


TRADUTTORI = {Connessione.WHATSAPP: WhatsApp, Connessione.TELEGRAM: Telegram}


# --- arrivo ---

def _conversazione(c, e):
    """Quella aperta con questa persona, o una nuova. Dopo 24 ore di silenzio si riparte: l'AI torna a rispondere."""
    s = c.sportello
    conv = (ConversazioneEsterna.objects.select_related("canale", "sportello")
            .filter(connessione=c, id_esterno=e.mittente, chiusa__isnull=True).first())
    if conv is not None:
        if conv.ultimo_in_arrivo and timezone.now() - conv.ultimo_in_arrivo > FINESTRA_WHATSAPP and assistente_sito.usa_ai(s):
            conv.gestita_da, conv.risposte_ai = ConversazioneEsterna.AI, 0
            conv.save(update_fields=["gestita_da", "risposte_ai"])
        return conv, False
    nome = " ".join(e.nome.split())[:80] or f"Cliente {e.mittente[-4:]}"
    conv = livechat.crea_conversazione(s, nome, origine=c.tipo, connessione=c, id_esterno=e.mittente, impronta_ip=f"{c.tipo}:{c.pk}",
                                       pagina=c.nome, usa_ai=assistente_sito.usa_ai(s))
    return conv, True


def _benvenuto(conv):
    """Al primo contatto dice subito con chi si sta parlando."""
    s = conv.sportello
    if conv.gestita_da == ConversazioneEsterna.AI:
        persona = " Scrivi «persona» quando vuoi parlare con un collega." if s.modalita == Sportello.AI else ""
        assistente_sito._dall_ai(conv, f"{s.benvenuto}\n\nSono un'intelligenza artificiale e posso sbagliare.{persona}")


def _ricevi_messaggio(c, e):
    try:
        with transaction.atomic():
            EventoEsterno.objects.create(connessione=c, id_esterno=e.id)
    except IntegrityError:
        return False                               # le piattaforme ripetono i messaggi: se ne conta uno
    conv, nuova = _conversazione(c, e)
    ConversazioneEsterna.objects.filter(pk=conv.pk).update(ultimo_in_arrivo=timezone.now())
    conv.ultimo_in_arrivo = timezone.now()
    testo = e.testo.strip()
    if nuova:
        _benvenuto(conv)
    if testo == "/start":                          # Telegram lo manda da solo all'apertura del bot
        return True
    if testo.lower() in CHIEDE_PERSONA and conv.gestita_da == ConversazioneEsterna.AI and conv.sportello.modalita == Sportello.AI:
        livechat.servizi.invia(conv.canale, None, testo, esterno=conv.nome, silenzioso=True)
        assistente_sito.passa_a_persona(conv, "Il cliente ha chiesto di parlare con una persona")
        return True
    if not testo:
        # niente file per ora: chi scrive deve saperlo, e chi risponde vede che è arrivato qualcosa
        livechat.servizi.invia(conv.canale, None, f"(ha inviato un contenuto di tipo «{e.tipo}», che per ora non si può leggere)",
                               esterno=conv.nome, silenzioso=conv.gestita_da == ConversazioneEsterna.AI)
        if conv.gestita_da == ConversazioneEsterna.AI:
            assistente_sito._dall_ai(conv, "Per ora so leggere solo i messaggi di testo: puoi scrivermi la tua richiesta?")
        return True
    livechat._dal_visitatore(conv, testo[:livechat.MASSIMO_TESTO])
    return True


def _aggiorna_stato(c, s):
    """Consegnato, letto o non riuscito, come lo dice la piattaforma. L'operatore lo vede sotto il messaggio."""
    m = Messaggio.objects.filter(id_uscita=s.id, canale__esterna__connessione=c).select_related("canale").first()
    if m is None:
        return
    ordine = {Messaggio.INVIATO: 1, Messaggio.CONSEGNATO: 2, Messaggio.LETTO: 3}
    mappa = {"sent": Messaggio.INVIATO, "delivered": Messaggio.CONSEGNATO, "read": Messaggio.LETTO, "failed": Messaggio.NON_RIUSCITO}
    nuovo = mappa.get(s.stato)
    if nuovo is None or (nuovo in ordine and ordine.get(m.consegna, 0) >= ordine[nuovo]):
        return                                     # gli stati possono arrivare in disordine
    Messaggio.objects.filter(pk=m.pk).update(consegna=nuovo, consegna_errore=s.errore[:200])
    eventi.emetti("agg", m.canale, m=m.pk)


def ricevi(c, corpo, intestazioni):
    """Da qui passa tutto ciò che arriva, vero o simulato: (codice HTTP, cosa è successo)."""
    if len(corpo) > MASSIMO_CORPO:
        return 413, "troppo grande"
    traduttore = TRADUTTORI[c.tipo]
    if not traduttore.autentica(c, corpo, intestazioni):
        log.warning("%s: firma non valida sulla connessione %s", c.tipo, c.pk)
        return 403, "firma non valida"
    try:
        dati = json.loads(corpo)
    except ValueError:
        return 400, "non è JSON"
    entrate, stati = traduttore.leggi(c, dati)
    nuovi = sum(1 for e in entrate if _ricevi_messaggio(c, e))
    for s in stati:
        _aggiorna_stato(c, s)
    Connessione.objects.filter(pk=c.pk).update(ultimo_evento=timezone.now())
    return 200, f"messaggi nuovi: {nuovi}, ripetuti: {len(entrate) - nuovi}, stati: {len(stati)}"


def _connessione(chiave, tipo):
    c = Connessione.objects.select_related("sportello").filter(chiave=chiave, tipo=tipo, attiva=True).first()
    if c is None:
        raise Http404
    return c


@csrf_exempt
def webhook_whatsapp(request, chiave):
    c = _connessione(chiave, Connessione.WHATSAPP)
    if request.method == "GET":                    # la verifica che Meta fa quando si registra l'indirizzo
        if request.GET.get("hub.mode") == "subscribe" and hmac.compare_digest(request.GET.get("hub.verify_token", ""), c.verifica):
            return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponse(status=405)
    codice, esito = ricevi(c, request.body, request.headers)
    return HttpResponse(esito if codice != 200 else "", status=codice)


@csrf_exempt
@require_POST
def webhook_telegram(request, chiave):
    codice, esito = ricevi(_connessione(chiave, Connessione.TELEGRAM), request.body, request.headers)
    return HttpResponse(esito if codice != 200 else "", status=codice)


# --- partenza ---

def _manda(c, url, intestazioni, dati):
    """Una connessione di prova non esce mai in rete."""
    if c.sandbox:
        from . import sandbox
        return sandbox.api(c, dati)
    try:
        r = httpx.post(url, headers=intestazioni, json=dati, timeout=15, trust_env=False)
    except httpx.HTTPError as e:
        raise ErroreConsegna(f"{TRADUTTORI[c.tipo].NOME} non raggiungibile", temporaneo=True) from e
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def _pezzi(testo):
    return [testo[i:i + MASSIMO_TESTO] for i in range(0, len(testo), MASSIMO_TESTO)] or [""]


def _invia_testo(c, destinatario, testo):
    """L'id dell'ultimo pezzo inviato."""
    traduttore, identificativo = TRADUTTORI[c.tipo], ""
    for pezzo in _pezzi(testo):
        url, intestazioni, dati = traduttore.richiesta(c, destinatario, pezzo)
        identificativo = traduttore.risposta(*_manda(c, url, intestazioni, dati))
    return identificativo


def accoda(messaggio):
    """Da chiamare per ogni messaggio che deve uscire verso il cliente."""
    Messaggio.objects.filter(pk=messaggio.pk).update(consegna=Messaggio.IN_CODA)
    pk = messaggio.pk
    transaction.on_commit(lambda: lavori.accoda("discuss.connettori.consegna", messaggio=pk))


def _esito(m, stato, errore=""):
    Messaggio.objects.filter(pk=m.pk).update(consegna=stato, consegna_errore=errore[:200])
    eventi.emetti("agg", m.canale, m=m.pk)


def consegna(messaggio):
    """Lavoro in background. Gli errori temporanei si ritentano, gli altri si mostrano all'operatore."""
    m = Messaggio.objects.select_related("canale").filter(pk=messaggio, eliminato=False).first()
    conv = ConversazioneEsterna.objects.select_related("connessione").filter(canale_id=m.canale_id).first() if m else None
    if conv is None or conv.connessione is None:
        return "niente"
    c = conv.connessione
    if not m.corpo:
        _esito(m, Messaggio.NON_RIUSCITO, "Gli allegati non si possono ancora inviare")
        return "allegato"
    if conv.fuori_finestra:
        _esito(m, Messaggio.FUORI_FINESTRA, "Sono passate più di 24 ore dall'ultimo messaggio del cliente")
        return "fuori finestra"
    try:
        identificativo = _invia_testo(c, conv.id_esterno, m.corpo)
    except ErroreConsegna as e:
        _esito(m, Messaggio.NON_RIUSCITO, str(e))
        Connessione.objects.filter(pk=c.pk).update(ultimo_errore=str(e)[:300])
        if e.temporaneo:
            raise                                  # il lavoro riprova più tardi
        return "non riuscita"
    Messaggio.objects.filter(pk=m.pk).update(consegna=Messaggio.INVIATO, consegna_errore="", id_uscita=identificativo[:128])
    eventi.emetti("agg", m.canale, m=m.pk)
    return "inviato"


consegna.senza_transazione = True


def saluto_di_chiusura(conv):
    if conv.connessione_id and not conv.fuori_finestra:
        lavori.accoda("discuss.connettori.manda_avviso", conversazione=conv.pk, testo="Questa conversazione è stata chiusa. Scrivici di nuovo quando vuoi.")


def manda_avviso(conversazione, testo):
    conv = ConversazioneEsterna.objects.select_related("connessione").filter(pk=conversazione).first()
    if conv is None or conv.connessione is None:
        return "niente"
    try:
        _invia_testo(conv.connessione, conv.id_esterno, testo)
    except ErroreConsegna as e:
        if e.temporaneo:
            raise
        return "non riuscita"
    return "inviato"


manda_avviso.senza_transazione = True


def pulisci():
    limite = timezone.now() - datetime.timedelta(days=GIORNI_EVENTI)
    return f"eventi tolti: {EventoEsterno.objects.filter(creato__lt=limite).delete()[0]}"


# --- messa in funzione ---

def url_webhook(c, base=None):
    nome = "discuss:wa_webhook" if c.tipo == Connessione.WHATSAPP else "discuss:tg_webhook"
    return (base or settings.SITO_URL).rstrip("/") + reverse(nome, args=[c.chiave])


def registra_telegram(c):
    """Dice a Telegram dove mandare i messaggi. Telegram accetta solo indirizzi HTTPS."""
    url = url_webhook(c)
    if not url.startswith("https://"):
        raise ErroreConsegna("Telegram accetta solo indirizzi HTTPS: SITO_URL non lo è.")
    r = httpx.post(f"https://api.telegram.org/bot{c.token()}/setWebhook", timeout=15, trust_env=False,
                   json={"url": url, "secret_token": c.segreto(), "allowed_updates": ["message"]})
    dati = r.json()
    if not dati.get("ok"):
        raise ErroreConsegna(dati.get("description") or f"Errore {r.status_code}")


@login_required
@require_POST
def registra_vista(request, pk):
    if not request.user.has_perm("discuss.change_connessione"):
        raise PermissionDenied
    c = get_object_or_404(Connessione, pk=pk, tipo=Connessione.TELEGRAM, sandbox=False)
    try:
        registra_telegram(c)
        messages.success(request, "Collegato: Telegram manderà qui i messaggi del bot.")
    except (ErroreConsegna, httpx.HTTPError, ValueError) as e:
        messages.error(request, f"Telegram non ha accettato: {e}")
    return redirect("discuss:connessioni_dettaglio", pk=c.pk)


