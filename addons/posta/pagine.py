"""La pagina «Posta e calendario» di ogni utente: collegare la propria casella Google o Microsoft (OAuth con PKCE),
scegliere che cosa passa, scollegarla, e il feed segreto del calendario. Ognuno vede e tocca solo le proprie."""
import datetime
import secrets
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import cifratura, lavori

from . import fornitori
from .fornitori.base import ErrorePosta
from .models import Casella, FeedCalendario, ServizioOAuth

SESSIONE = "posta.oauth"
DURATA = 600                  # secondi per tornare dal servizio


def _ritorno(request):
    return request.build_absolute_uri(reverse("posta:ritorno"))


@login_required
@permission_required("posta.add_casella", raise_exception=True)
def caselle(request):
    feed = FeedCalendario.objects.filter(utente=request.user).first()
    caselle = list(Casella.objects.filter(utente=request.user).select_related("azienda"))
    for c in caselle:
        c.puo_inviare = fornitori.FORNITORI[c.tipo].AMBITO_INVIO.lower() in (c.ambiti or "").lower()
    return render(request, "posta/caselle.html", {
        "caselle": caselle,
        "servizi": ServizioOAuth.objects.filter(attivo=True).exclude(tipo__in=Casella.objects.filter(utente=request.user).values("tipo")),
        "nessun_servizio": not ServizioOAuth.objects.filter(attivo=True).exists(),
        "feed": request.build_absolute_uri(reverse("posta:feed", args=[feed.token])) if feed else "",
        "ritorno": _ritorno(request) if request.user.has_perm("posta.change_serviziooauth") else "",
    })


@login_required
@permission_required("posta.add_casella", raise_exception=True)
@require_POST
def collega(request, tipo):
    servizio = ServizioOAuth.objects.filter(tipo=tipo, attivo=True).first()
    if servizio is None or getattr(request, "azienda", None) is None:
        raise Http404
    stato, verificatore = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    request.session[SESSIONE] = {"tipo": tipo, "stato": stato, "verificatore": verificatore, "azienda": request.azienda.pk, "t": time.time()}
    return redirect(fornitori.per(servizio).url_autorizzazione(_ritorno(request), stato, verificatore))


@login_required
@permission_required("posta.add_casella", raise_exception=True)
def ritorno(request):
    attesa = request.session.pop(SESSIONE, None) or {}
    if request.GET.get("error"):
        messages.warning(request, "Collegamento annullato: non hai dato il consenso.")
        return redirect("posta:caselle")
    if (not attesa or not secrets.compare_digest(attesa.get("stato", ""), request.GET.get("state", ""))
            or time.time() - attesa.get("t", 0) > DURATA):
        messages.error(request, "Richiesta non riconosciuta o scaduta: riprova a collegare la casella.")
        return redirect("posta:caselle")
    servizio = get_object_or_404(ServizioOAuth, tipo=attesa["tipo"], attivo=True)
    try:
        dati = fornitori.per(servizio).scambia(request.GET.get("code", ""), _ritorno(request), attesa["verificatore"])
    except ErrorePosta as e:
        messages.error(request, str(e))
        return redirect("posta:caselle")
    try:
        with transaction.atomic():
            casella, nuova = Casella.objects.update_or_create(utente=request.user, tipo=servizio.tipo, defaults={
                "azienda_id": attesa["azienda"], "email": dati["email"], "refresh_cifrato": cifratura.cifra(dati["refresh"]),
                "accesso_cifrato": cifratura.cifra(dati["accesso"]), "accesso_scade": dati["scade"], "ambiti": dati["ambiti"], "in_errore": False,
                "ultimo_esito": ""})
    except IntegrityError:
        messages.error(request, "Non è stato possibile salvare la casella: riprova.")
        return redirect("posta:caselle")
    transaction.on_commit(lambda: lavori.accoda("posta.sincronia.giro", casella_id=casella.pk, max_tentativi=2))
    messages.success(request, f"{casella.email} collegata: le email con i clienti e gli appuntamenti arrivano entro pochi minuti.")
    return redirect("posta:caselle")


def _mia(request, pk):
    return get_object_or_404(Casella, pk=pk, utente=request.user)


@login_required
@require_POST
def imposta(request, pk):
    casella = _mia(request, pk)
    casella.posta, casella.calendario = request.POST.get("posta") == "on", request.POST.get("calendario") == "on"
    casella.invio = request.POST.get("invio") == "on"
    casella.save(update_fields=["posta", "calendario", "invio"])
    messages.success(request, "Preferenze salvate.")
    return redirect("posta:caselle")


@login_required
@require_POST
def sincronizza(request, pk):
    casella = _mia(request, pk)
    lavori.accoda("posta.sincronia.giro", casella_id=casella.pk, azienda=casella.azienda, utente=request.user, max_tentativi=1)
    messages.success(request, "Sincronizzazione avviata: l'esito compare qui sotto.")
    return redirect("posta:caselle")


@login_required
@require_POST
def scollega(request, pk):
    """Si dimenticano i token. Email ed eventi già passati restano: sono nello storico dei clienti."""
    casella = _mia(request, pk)
    email, tipo = casella.email, casella.get_tipo_display()
    casella.delete()
    messages.success(request, f"{email} scollegata. Per togliere del tutto l'accesso, rimuovi l'app anche dalle impostazioni del tuo account {tipo}.")
    return redirect("posta:caselle")


@login_required
@permission_required("posta.add_casella", raise_exception=True)
@require_POST
def feed_rinnova(request):
    feed, nuovo = FeedCalendario.objects.get_or_create(utente=request.user)
    if not nuovo:
        feed.rinnova()
    messages.success(request, "Nuovo indirizzo del feed: il vecchio non funziona più." if not nuovo else "Feed del calendario creato.")
    return redirect("posta:caselle")


def feed(request, token):
    """Il calendario dell'utente da abbonare: gli eventi che organizza o a cui partecipa, dagli ultimi tre mesi in poi.
    Senza accesso: l'indirizzo segreto basta, come per i calendari di Google e Outlook."""
    from calendario.ics import calendario
    from calendario.models import Evento
    voce = FeedCalendario.objects.select_related("utente").filter(token=token, utente__is_active=True).first()
    if voce is None:
        raise Http404
    utente = voce.utente
    da = timezone.now() - datetime.timedelta(days=90)
    eventi = (Evento.objects.filter(fine__gte=da).filter(organizzatore=utente) | Evento.objects.filter(fine__gte=da, partecipanti=utente))
    eventi = eventi.distinct().select_related("organizzatore").prefetch_related("partecipanti").order_by("inizio")[:2000]
    nome = f"adabox · {utente.get_full_name() or utente.username}"
    risposta = HttpResponse(calendario(eventi, nome), content_type="text/calendar; charset=utf-8")
    risposta["Cache-Control"] = "private, max-age=300"
    return risposta
