"""Portale clienti: il cliente (utente esterno con un accesso legato al suo contatto) vede i ticket e i progetti
della sua azienda, apre ticket, risponde e allega file. Vede solo i messaggi pubblici: mai le note interne, i
tracciamenti o gli eventi di sistema. Gli utenti interni non entrano qui: hanno l'helpdesk."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST

from contatti.models import Contatto
from core import allegati, chatter
from core.models import Allegato, Messaggio, ProfiloUtente
from helpdesk.models import FaseTicket, Ticket
from progetti.models import Progetto

from .instradamento import instrada
from .models import AccessoPortale, DatiTicket

MAX_ALLEGATI = 5


def _accesso(request):
    accesso = AccessoPortale.objects.filter(utente=request.user).select_related("contatto__societa").first()
    if accesso is None:
        raise PermissionDenied("Il portale è riservato ai clienti.")
    return accesso


def portale(vista):
    @login_required
    def interna(request, *args, **kwargs):
        request.accesso = _accesso(request)
        return vista(request, *args, **kwargs)
    interna.__name__ = vista.__name__
    return interna


def _ticket(accesso):
    return (Ticket.objects.filter(contatto__in=accesso.contatti()).select_related("fase", "contatto")
            .order_by("fase__chiusa", "-creato"))


def _progetti(accesso):
    return Progetto.objects.filter(cliente=accesso.cliente).order_by("nome")


def _contesto(request, **altro):
    return {"accesso": request.accesso, "cliente": request.accesso.cliente, **altro}


def _pubblici(ticket):
    return (Messaggio.objects.filter(content_type=ContentType.objects.get_for_model(Ticket), object_id=ticket.pk,
                                     tipo=Messaggio.MESSAGGIO)
            .select_related("autore").prefetch_related("allegati").order_by("creato", "pk"))


def _file(request, ticket):
    """Gli allegati del form (al massimo MAX_ALLEGATI, regole del kernel) salvati sul ticket."""
    caricati = []
    for f in request.FILES.getlist("file")[:MAX_ALLEGATI]:
        try:
            caricati.append(allegati.salva(ticket, f, request.user))
        except allegati.AllegatoNonValido as e:
            messages.error(request, str(e))
    return caricati


@portale
def home(request):
    ticket = _ticket(request.accesso)
    return render(request, "assistenza/portale/home.html", _contesto(
        request, ticket=ticket[:100], aperti=ticket.filter(fase__chiusa=False).count(),
        progetti=_progetti(request.accesso)))


@portale
def dettaglio(request, pk):
    ticket = get_object_or_404(_ticket(request.accesso), pk=pk)
    if request.method == "POST":
        testo = request.POST.get("testo", "").strip()[:10000]
        if not testo and not request.FILES.getlist("file"):
            messages.error(request, "Scrivi un messaggio o allega un file.")
            return redirect("assistenza:portale_ticket", pk=pk)
        with transaction.atomic():
            file = _file(request, ticket)
            chatter.scrivi(ticket, request.user, testo, allegati=file)
            if ticket.fase.chiusa:                         # il cliente risponde a un ticket chiuso: si riapre
                ticket.fase = FaseTicket.objects.filter(chiusa=False).order_by("ordine", "pk").first() or ticket.fase
                ticket.save(update_fields=["fase"])
        messages.success(request, "Messaggio inviato.")
        return redirect("assistenza:portale_ticket", pk=pk)
    dati = DatiTicket.objects.filter(ticket=ticket).select_related("progetto").first()
    return render(request, "assistenza/portale/ticket.html", _contesto(
        request, t=ticket, dati=dati, messaggi=_pubblici(ticket),
        allegati_ticket=Allegato.objects.filter(content_type=ContentType.objects.get_for_model(Ticket),
                                                object_id=ticket.pk, messaggi__isnull=True)
        .filter(Q(caricato_da__isnull=True) | Q(caricato_da=request.user))))


@portale
def nuovo(request):
    supportati = list(_progetti(request.accesso).filter(supporto__attivo=True))
    if request.method == "POST":
        oggetto = request.POST.get("oggetto", "").strip()[:200]
        progetto = next((p for p in supportati if str(p.pk) == request.POST.get("progetto")), None)
        tipo = request.POST.get("tipo") if request.POST.get("tipo") in dict(DatiTicket.TIPI) else DatiTicket.BUG
        if not oggetto or progetto is None:
            messages.error(request, "Scegli il progetto e scrivi l'oggetto.")
        else:
            with transaction.atomic():
                ticket = Ticket.objects.create(
                    azienda=progetto.azienda, oggetto=oggetto, descrizione=request.POST.get("descrizione", "")[:10000],
                    contatto=request.accesso.contatto, email_cliente=request.user.email)
                instrada(ticket, progetto=progetto, canale=DatiTicket.PORTALE, tipo=tipo, forza=True)
                _file(request, ticket)
                chatter.segui(ticket, request.user)
            messages.success(request, f"Segnalazione {ticket.numero} inviata: ti risponderemo qui e per email.")
            return redirect("assistenza:portale_ticket", pk=ticket.pk)
    return render(request, "assistenza/portale/nuovo.html", _contesto(request, progetti=supportati,
                                                                      tipi=DatiTicket.TIPI))


@portale
def progetti(request):
    elenco = _progetti(request.accesso)
    aperti = {p: Ticket.objects.filter(assistenza__progetto=p, fase__chiusa=False).count() for p in elenco}
    return render(request, "assistenza/portale/progetti.html", _contesto(request, progetti=aperti.items()))


@portale
def scarica(request, pk, allegato):
    """Un allegato di un ticket visibile, solo se è in un messaggio pubblico o l'ha caricato il cliente."""
    ticket = get_object_or_404(_ticket(request.accesso), pk=pk)
    file = get_object_or_404(Allegato, pk=allegato, content_type=ContentType.objects.get_for_model(Ticket),
                             object_id=ticket.pk)
    pubblico = file.messaggi.filter(tipo=Messaggio.MESSAGGIO).exists()
    if not (pubblico or file.caricato_da_id in (None, request.user.pk)):
        raise Http404
    return allegati.risposta(file)


# ---------- invito (dagli utenti interni, dalla scheda del contatto) ----------

def link_password(utente):
    uid = urlsafe_base64_encode(force_bytes(utente.pk))
    return settings.SITO_URL + reverse("password_reset_confirm", args=[uid, default_token_generator.make_token(utente)])


def invita(contatto, da_utente):
    """Crea (o riattiva) l'utente esterno del contatto e gli manda il link per scegliere la password."""
    if not contatto.email:
        raise ValueError("Il contatto non ha un indirizzo email.")
    Utente = get_user_model()
    accesso = AccessoPortale.objects.filter(contatto=contatto).select_related("utente").first()
    if accesso is None:
        if Utente.objects.filter(username__iexact=contatto.email).exists():
            raise ValueError(f"Esiste già un utente {contatto.email}: non può diventare un accesso al portale.")
        utente = Utente.objects.create_user(contatto.email.lower(), contatto.email, get_random_string(32),
                                            first_name=contatto.nome[:150])
        ProfiloUtente.objects.update_or_create(utente=utente, defaults={"esterno": True})
        accesso = AccessoPortale.objects.create(utente=utente, contatto=contatto, invitato_da=da_utente)
    utente = accesso.utente
    if not utente.is_active:
        utente.is_active = True
        utente.save(update_fields=["is_active"])
    marchio = settings.THEME.get("brand", "")
    send_mail(f"Il tuo accesso al portale clienti di {marchio}",
              f"Ciao {contatto.nome},\n\nda qui segui le richieste di assistenza e i progetti di {accesso.cliente} e "
              f"ne apri di nuove.\n\nScegli la tua password:\n{link_password(utente)}\n\n"
              f"Poi entri da {settings.SITO_URL}{reverse('login')} con il nome utente {utente.username}.\n",
              None, [contatto.email])
    return accesso


@login_required
@require_POST
def invita_contatto(request, pk):
    if not request.user.has_perm("assistenza.add_accessoportale"):
        raise PermissionDenied
    contatto = get_object_or_404(Contatto, pk=pk)
    try:
        invita(contatto, request.user)
    except ValueError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Invito al portale mandato a {contatto.email}.")
    return redirect("contatti:contatti_dettaglio", pk=pk)


@login_required
@require_POST
def revoca_contatto(request, pk):
    if not request.user.has_perm("assistenza.delete_accessoportale"):
        raise PermissionDenied
    accesso = get_object_or_404(AccessoPortale, contatto_id=pk)
    accesso.utente.is_active = False
    accesso.utente.save(update_fields=["is_active"])
    messages.success(request, f"Accesso al portale di {accesso.contatto} sospeso.")
    return redirect("contatti:contatti_dettaglio", pk=pk)

