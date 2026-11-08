"""Accesso al portale con Google o Microsoft. Entra solo chi ha già un accesso al portale (invitato) con quella email,
attivo: niente registrazioni. Il primo accesso collega l'account all'utente: da Google, se l'email è verificata, subito;
da Microsoft (dove l'email non è garantita) solo dopo aver confermato con il link mandato all'indirizzo dell'invito.
Chi ha la verifica in due passaggi la fa anche qui."""
import logging
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.core import signing
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core import due_fattori as df2
from core import modelli_email

from . import oidc
from .models import AccessoPortale, IdentitaEsterna, ProviderAccesso

log = logging.getLogger("portale.accesso")
SESSIONE = "portale_oidc"
SALE = "portale.collega"
BACKEND = "django.contrib.auth.backends.ModelBackend"


def attivi():
    return list(ProviderAccesso.objects.filter(attivo=True).exclude(client_id=""))


def _ritorno(request, provider):
    return settings.SITO_URL + reverse("portale:accedi_ritorno", args=[provider.tipo])


def _provider(tipo):
    p = ProviderAccesso.objects.filter(tipo=tipo, attivo=True).first()
    if p is None:
        raise Http404
    return p


def accedi(request, tipo):
    provider = _provider(tipo)
    try:
        url, dati = oidc.inizia(provider, _ritorno(request, provider))
    except oidc.ErroreOidc as e:
        log.warning("accesso %s: %s", tipo, e)
        messages.error(request, f"{provider} non risponde: accedi con la password o riprova più tardi.")
        return redirect("login")
    request.session[SESSIONE] = dati
    return redirect(url)


def _utente_portale(email):
    accesso = (AccessoPortale.objects.filter(utente__email__iexact=email, utente__is_active=True)
               .select_related("utente").first()) if email else None
    return accesso.utente if accesso else None


def _entra(request, utente):
    df = df2.di(utente)
    if df is not None and df.attiva_dal is not None and not df2.dispositivo_fidato(request, df):
        from core.due_fattori_viste import ATTESA
        request.session[ATTESA] = {"u": utente.pk, "b": BACKEND, "t": time.time(), "next": reverse("portale:home")}
        return redirect("due_fattori_accesso")
    login(request, utente, backend=BACKEND)
    return redirect("portale:home")


def ritorno(request, tipo):
    provider = _provider(tipo)
    sessione = request.session.pop(SESSIONE, None)
    if request.GET.get("error"):
        messages.info(request, "Accesso annullato.")
        return redirect("login")
    try:
        soggetto, email, verificata, nome = oidc.completa(provider, sessione, request.GET.get("state"), request.GET.get("code"),
                                                          _ritorno(request, provider))
    except oidc.ErroreOidc as e:
        log.warning("accesso %s non riuscito: %s", tipo, e)
        messages.error(request, f"Accesso con {provider} non riuscito: {e}.")
        return redirect("login")
    identita = IdentitaEsterna.objects.filter(tipo=tipo, soggetto=soggetto).select_related("utente").first()
    if identita is not None:
        utente = identita.utente
        if not utente.is_active or not AccessoPortale.objects.filter(utente=utente).exists():
            messages.error(request, "Il tuo accesso al portale è sospeso.")
            return redirect("login")
        identita.ultimo_accesso = timezone.now()
        identita.save(update_fields=["ultimo_accesso"])
        return _entra(request, utente)
    utente = _utente_portale(email)
    if utente is None:
        messages.error(request, f"Non c'è un accesso al portale per {email or 'questo account'}: chiedi un invito a chi ti segue.")
        return redirect("login")
    if verificata:
        IdentitaEsterna.objects.create(utente=utente, tipo=tipo, soggetto=soggetto, email=email, ultimo_accesso=timezone.now())
        return _entra(request, utente)
    token = signing.dumps({"u": utente.pk, "t": tipo, "s": soggetto, "e": email}, salt=SALE)
    link = settings.SITO_URL + reverse("portale:accedi_conferma", args=[token])
    accesso = utente.accesso_portale
    modelli_email.messaggio("portale.collega", accesso.azienda, {"nome": utente.first_name or email, "servizio": str(provider),
                                                                 "link": link}, [utente.email]).send(fail_silently=True)
    return render(request, "portale/accesso_conferma.html", {"inviata": True, "email": utente.email, "servizio": provider})


def conferma(request, token):
    """Il link dell'email: la pagina non cambia nulla in GET (i filtri antispam aprono i link), collega col POST."""
    try:
        dati = signing.loads(token, salt=SALE, max_age=24 * 3600)
    except signing.BadSignature:
        return render(request, "portale/accesso_conferma.html", {"scaduto": True}, status=400)
    utente = get_object_or_404(get_user_model(), pk=dati["u"], is_active=True, email__iexact=dati["e"])
    servizio = dict(ProviderAccesso.TIPI).get(dati["t"], dati["t"])
    if request.method == "POST":
        IdentitaEsterna.objects.get_or_create(tipo=dati["t"], soggetto=dati["s"], defaults={"utente": utente, "email": dati["e"]})
        messages.success(request, f"Account {servizio} collegato: da ora entri con «Accedi con {servizio}».")
        return redirect("login")
    return render(request, "portale/accesso_conferma.html", {"conferma": True, "servizio": servizio, "email": dati["e"]})
