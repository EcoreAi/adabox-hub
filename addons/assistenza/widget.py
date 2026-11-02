"""Endpoint pubblico del widget di segnalazione: l'applicazione del cliente manda la segnalazione con la chiave del
progetto; nasce un ticket instradato al team del progetto, con i dati tecnici e lo screenshot.

Controlli: progetto con assistenza attiva e siti ammessi (CORS: l'origine deve essere tra i siti del supporto),
al massimo LIMITE_ORA segnalazioni l'ora per indirizzo, campo esca contro i bot, dimensioni dei campi.

L'email è solo dichiarata: il ticket non si lega a un contatto (e non compare nel portale di nessuno) finché chi
scrive non conferma l'indirizzo con il link firmato che riceve."""
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core import signing
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from contatti.models import Contatto
from core import allegati
from helpdesk.models import Ticket

from .instradamento import instrada
from .models import DatiTicket, Supporto

log = logging.getLogger("assistenza.widget")

LIMITE_ORA = 10
MAX_SCREENSHOT_MB = 5
TIPI = {t for t, _ in DatiTicket.TIPI}
SALE_CONFERMA = "assistenza.widget.email"
GIORNI_CONFERMA = 30
CAMPI_TECNICI = ("pagina", "browser", "schermo", "finestra", "lingua", "versione", "errori", "utente_app")


def _origine(request):
    return (request.headers.get("Origin") or "").rstrip("/").lower()


def _cors(risposta, origine):
    if origine:
        risposta["Access-Control-Allow-Origin"] = origine
        risposta["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        risposta["Access-Control-Allow-Headers"] = "Content-Type"
        risposta["Access-Control-Max-Age"] = "600"
        risposta["Vary"] = "Origin"
    return risposta


def _errore(messaggio, origine, stato=400):
    return _cors(JsonResponse({"ok": False, "errore": messaggio}, status=stato), origine)


def _ip(request):
    inoltrato = request.headers.get("X-Forwarded-For", "")
    return (inoltrato.split(",")[0].strip() if inoltrato else request.META.get("REMOTE_ADDR", ""))[:45]


def _tecnici(testo, ip):
    try:
        dati = json.loads(testo or "{}")
    except ValueError:
        dati = {}
    dati = dati if isinstance(dati, dict) else {}
    pulito = {k: str(dati[k])[:2000] for k in CAMPI_TECNICI if dati.get(k) not in (None, "", [])}
    pulito["ip"] = ip
    return pulito


def _contatto(ticket, email, nome):
    contatto = Contatto.objects.filter(azienda=ticket.azienda, email__iexact=email).order_by("pk").first()
    if contatto is None:
        progetto = ticket.assistenza.progetto
        contatto = Contatto.objects.create(azienda=ticket.azienda, tipo=Contatto.PERSONA, nome=nome or email,
                                           email=email, societa=progetto.cliente if progetto else None)
    return contatto


def link_conferma(ticket, email, nome):
    token = signing.dumps({"t": ticket.pk, "e": email.lower(), "n": nome}, salt=SALE_CONFERMA)
    return f"{settings.SITO_URL}{reverse('assistenza:widget_conferma', args=[token])}"


def conferma_email(request, token):
    """La pagina non cambia nulla in GET (i filtri antispam aprono i link): la conferma è il POST del bottone."""
    try:
        dati = signing.loads(token, salt=SALE_CONFERMA, max_age=GIORNI_CONFERMA * 86400)
    except signing.BadSignature:
        return render(request, "assistenza/conferma_email.html", {"scaduto": True}, status=400)
    ticket = (Ticket.objects.filter(pk=dati["t"], email_cliente__iexact=dati["e"], assistenza__canale=DatiTicket.WIDGET)
              .select_related("assistenza__progetto__cliente").first())
    if ticket is None:
        return render(request, "assistenza/conferma_email.html", {"scaduto": True}, status=400)
    confermata = ticket.contatto_id is not None
    if request.method == "POST" and not confermata:
        contatto = _contatto(ticket, dati["e"], dati.get("n"))
        Ticket.objects.filter(azienda=ticket.azienda, email_cliente__iexact=dati["e"], contatto=None,
                              assistenza__canale=DatiTicket.WIDGET).update(contatto=contatto)
        confermata = True
    return render(request, "assistenza/conferma_email.html", {"ticket": ticket, "confermata": confermata})


def _conferma(ticket, email, nome):
    try:
        send_mail(f"Segnalazione ricevuta: {ticket.numero}",
                  f"Abbiamo ricevuto la tua segnalazione «{ticket.oggetto}» con il numero {ticket.numero}.\n"
                  f"Ti scriveremo a questo indirizzo.\n\n"
                  f"Se hai l'accesso al portale clienti e vuoi seguirla da lì, conferma che l'indirizzo è tuo:\n"
                  f"{link_conferma(ticket, email, nome)}\n", None, [email], fail_silently=True)
    except Exception:
        log.exception("conferma del ticket %s", ticket.pk)


@csrf_exempt
def segnala(request, chiave):
    origine = _origine(request)
    supporto = Supporto.objects.filter(chiave=chiave, attivo=True).select_related("progetto__cliente").first()
    if supporto is None or not supporto.elenco_domini():
        return _errore("widget non attivo", origine, 404)
    if origine not in supporto.elenco_domini():
        log.warning("widget %s: origine non ammessa %r", supporto.pk, origine)
        return _errore("sito non ammesso", "", 403)
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204), origine)
    if request.method != "POST":
        return _errore("solo POST", origine, 405)
    if request.POST.get("sito_web"):                       # campo esca: lo compila solo un bot
        return _cors(JsonResponse({"ok": True, "numero": ""}), origine)
    ip = _ip(request)
    un_ora_fa = timezone.now() - timedelta(hours=1)
    recenti = DatiTicket.objects.filter(canale=DatiTicket.WIDGET, tecnici__ip=ip, ticket__creato__gte=un_ora_fa)
    if recenti.count() >= LIMITE_ORA:
        return _errore("troppe segnalazioni: riprova più tardi", origine, 429)
    oggetto = (request.POST.get("oggetto") or "").strip()[:200]
    descrizione = (request.POST.get("descrizione") or "").strip()[:10000]
    email = (request.POST.get("email") or "").strip()[:254]
    nome = (request.POST.get("nome") or "").strip()[:200]
    tipo = request.POST.get("tipo") if request.POST.get("tipo") in TIPI else DatiTicket.BUG
    if not oggetto:
        return _errore("scrivi l'oggetto della segnalazione", origine)
    try:
        validate_email(email)
    except ValidationError:
        return _errore("serve un indirizzo email valido per risponderti", origine)
    screenshot = request.FILES.get("screenshot")
    if screenshot is not None and (screenshot.size > MAX_SCREENSHOT_MB * 1024 * 1024
                                   or not (screenshot.content_type or "").startswith("image/")):
        return _errore(f"lo screenshot deve essere un'immagine di al massimo {MAX_SCREENSHOT_MB} MB", origine)
    ticket = Ticket.objects.create(azienda=supporto.azienda, oggetto=oggetto, descrizione=descrizione,
                                   email_cliente=email)
    instrada(ticket, progetto=supporto.progetto, canale=DatiTicket.WIDGET, tipo=tipo,
             tecnici=_tecnici(request.POST.get("tecnici"), ip), forza=True)
    if screenshot is not None:
        try:
            allegati.salva(ticket, screenshot)
        except allegati.AllegatoNonValido as e:
            log.info("screenshot del ticket %s non salvato: %s", ticket.pk, e)
    _conferma(ticket, email, nome)
    return _cors(JsonResponse({"ok": True, "numero": ticket.numero}), origine)
