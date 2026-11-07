"""Condividere con i colleghi un documento scritto con Ada, un grafico o una tabella della chat.

Chi riceve legge e scarica, non modifica: il documento resta di chi l'ha scritto (e delle sue versioni). Grafici e
tabelle si ricalcolano con i permessi di chi guarda, mai con quelli di chi ha condiviso: un collega non vede dati che
non potrebbe vedere da sé. Chi riceve trova la cosa in Preferiti → «Condivisi con me», un'email e, se c'è Discuss, una
notifica nella posta in arrivo."""
import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.urls import reverse

from .models import Artifact, DocumentoChat

log = logging.getLogger("ai.condivisione")

TIPI = {"documento": DocumentoChat, "artifact": Artifact}


def colleghi(request, oggetto):
    """[{pk, nome, dentro}] di chi può ricevere: i colleghi attivi dell'azienda corrente, non i clienti del portale."""
    azienda = getattr(request, "azienda", None)
    if azienda is None:
        return []
    dentro = set(oggetto.condiviso_con.values_list("pk", flat=True))
    utenti = (get_user_model().objects.filter(is_active=True, profilo__aziende=azienda).exclude(profilo__esterno=True)
              .exclude(pk=oggetto.utente_id).order_by("first_name", "last_name", "username"))
    return [{"pk": u.pk, "nome": u.get_full_name() or u.get_username(), "dentro": u.pk in dentro} for u in utenti]


def url_di(oggetto):
    if isinstance(oggetto, DocumentoChat):
        return reverse("ai:documento_condiviso", args=[oggetto.pk])
    return reverse("ai:artifact", args=[oggetto.pk])


def nome_di(oggetto):
    if isinstance(oggetto, DocumentoChat):
        return f"il documento «{oggetto.titolo}»"
    return f"{'il grafico' if oggetto.tipo == Artifact.GRAFICO else 'la tabella'} «{oggetto.titolo}»"


def condividi(request, oggetto, scelti):
    """Le persone con cui è condiviso diventano `scelti` (tra i colleghi ammessi); i nuovi ricevono l'avviso.
    Restituisce (con quanti è condiviso, nuovi)."""
    ammessi = {c["pk"] for c in colleghi(request, oggetto)}
    scelti = {int(i) for i in scelti if str(i).isdigit()} & ammessi
    nuovi = scelti - set(oggetto.condiviso_con.values_list("pk", flat=True))
    oggetto.condiviso_con.set(scelti)
    if nuovi:
        _avvisa(request.user, oggetto, get_user_model().objects.filter(pk__in=nuovi))
    return len(scelti), nuovi


def _avvisa(autore, oggetto, destinatari):
    chi = autore.get_full_name() or autore.get_username()
    titolo = f"{chi} ha condiviso con te {nome_di(oggetto)}"[:200]
    url = url_di(oggetto)
    email = [u.email for u in destinatari if u.email]
    if email:
        send_mail(titolo, f"{titolo}.\n{settings.SITO_URL}{url}", None, email, fail_silently=True)
    if apps.is_installed("discuss"):                # ai non dipende da Discuss: la posta in arrivo solo se c'è
        try:
            from discuss.notifiche import condivisione
            for u in destinatari:
                condivisione(u, autore, titolo, url)
        except Exception:                           # noqa: BLE001 - l'avviso non deve far fallire la condivisione
            log.exception("notifica di condivisione non creata")


def leggibile(modello, utente, pk):
    """L'oggetto se è dell'utente o condiviso con lui, altrimenti None (i documenti di chat nascoste mai)."""
    if not str(pk or "").isdigit():
        return None
    qs = modello.objects.filter(pk=pk)
    if modello is DocumentoChat:
        qs = qs.filter(conversazione__nascosta=False)
    return (qs.filter(utente=utente) | qs.filter(condiviso_con=utente)).distinct().first()


def ricevuti(utente):
    """(documenti, grafici e tabelle) condivisi con l'utente, i più recenti prima."""
    documenti = DocumentoChat.objects.filter(condiviso_con=utente, conversazione__nascosta=False).select_related("utente").order_by("-aggiornato")[:100]
    artifact = Artifact.objects.filter(condiviso_con=utente).select_related("utente").order_by("-pk")[:100]
    return documenti, artifact
