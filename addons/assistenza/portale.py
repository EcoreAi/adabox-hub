"""Le sezioni dell'assistenza nel portale clienti (modulo portale): il cliente vede i ticket e i progetti
della sua azienda, apre ticket, risponde e allega file. Vede solo i messaggi pubblici: mai le note interne, i
tracciamenti o gli eventi di sistema. Gli utenti interni non entrano qui: hanno l'helpdesk."""
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST

from contatti.models import Contatto
from core import allegati, chatter, modelli_email
from core.dashboard import queryset
from core.models import Allegato, Messaggio, ProfiloUtente
from helpdesk.guida import cerca
from helpdesk.models import Articolo, FaseTicket, Ticket
from helpdesk.pagine import _voto_dato, contesto_guida, registra_utilita
from portale.accesso import contesto as contesto_portale
from portale.accesso import portale
from progetti.models import Progetto

from .instradamento import instrada
from .models import DatiTicket

MAX_ALLEGATI = 5


def _ticket(accesso):
    return (Ticket.objects.filter(contatto__in=accesso.contatti()).select_related("fase", "contatto")
            .order_by("fase__chiusa", "-creato"))


def _progetti(accesso):
    return Progetto.objects.filter(cliente=accesso.cliente).order_by("nome")


def _contesto(request, **altro):
    return contesto_portale(request, **altro)


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


def _monte_ore(accesso):
    """I contratti con monte ore del cliente, se il modulo Commesse conta le ore."""
    if not apps.is_installed("commesse"):
        return []
    from commesse.operazioni import monte_ore
    from .models import Contratto
    return [monte_ore(c) for c in Contratto.objects.filter(cliente=accesso.cliente, attivo=True, ore_incluse__gt=0)]


@portale
def home(request):
    ticket = _ticket(request.accesso)
    return render(request, "assistenza/portale/home.html", _contesto(
        request, ticket=ticket[:100], aperti=ticket.filter(fase__chiusa=False).count(),
        progetti=_progetti(request.accesso), monti=_monte_ore(request.accesso)))


def _articoli(accesso):
    return Articolo.objects.filter(azienda=accesso.contatto.azienda, pubblicato=True)


@portale
def guida(request):
    return render(request, "assistenza/portale/guida.html", _contesto(
        request, **contesto_guida(_articoli(request.accesso), request.GET.get("q", "").strip()),
        url_articolo="assistenza:portale_articolo"))


@portale
def articolo(request, pk):
    voce = get_object_or_404(_articoli(request.accesso), pk=pk)
    Articolo.objects.filter(pk=pk).update(visite=F("visite") + 1)
    return render(request, "assistenza/portale/articolo.html", _contesto(
        request, articolo=voce, indietro=reverse("assistenza:portale_guida"),
        utile_url=reverse("assistenza:portale_utile", args=[pk]), voto_dato=_voto_dato(request, pk)))


@portale
@require_POST
def utile(request, pk):
    registra_utilita(request, _articoli(request.accesso), pk)
    return redirect("assistenza:portale_articolo", pk=pk)


@portale
def guida_cerca(request):
    return JsonResponse({"articoli": [{"titolo": a.titolo, "url": reverse("assistenza:portale_articolo", args=[a.pk])}
                                      for a in cerca(_articoli(request.accesso), request.GET.get("q", ""))]})


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
def progetto(request, pk):
    """La pagina del progetto per il cliente: avanzamento, milestone, rilasci e i soli compiti segnati come visibili."""
    from django.db.models import Count, Q

    from progetti.models import Compito
    p = get_object_or_404(_progetti(request.accesso), pk=pk)
    totale, completati, percentuale, _ = p.riepilogo_compiti()
    milestone = (p.milestone.annotate(totale=Count("compiti"), fatti=Count("compiti", filter=Q(compiti__fase__chiusa=True)))
                 .order_by("scadenza", "pk"))
    compiti = (Compito.objects.filter(progetto=p, visibile_cliente=True).select_related("fase", "milestone")
               .order_by("fase__chiusa", "scadenza", "pk"))
    richieste = Ticket.objects.filter(assistenza__progetto=p, contatto__in=request.accesso.contatti()).select_related("fase").order_by("fase__chiusa", "-creato")[:10]
    return render(request, "assistenza/portale/progetto.html", _contesto(
        request, p=p, totale=totale, completati=completati, percentuale=percentuale, compiti=compiti, richieste=richieste,
        milestone=[(m, round(100 * m.fatti / m.totale) if m.totale else 0) for m in milestone],
        rilasci=p.rilasci.order_by("-data_prevista", "-pk")))


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


def riepilogo_richieste(accesso):
    """Per la home del portale: le richieste aperte e le ultime aggiornate."""
    ticket = _ticket(accesso)
    aperte = ticket.filter(fase__chiusa=False)
    return {"conta": aperte.count(), "nota": "richieste aperte" if aperte.exists() else "Nessuna richiesta aperta.",
            "voci": [(f"{t.numero} · {t.oggetto}", reverse("assistenza:portale_ticket", args=[t.pk]), t.fase.nome) for t in aperte[:4]]}


def riepilogo_progetti(accesso):
    progetti = list(_progetti(accesso)[:4])
    return {"conta": _progetti(accesso).count(), "voci": [(p.nome, reverse("assistenza:portale_progetto", args=[p.pk]), p.get_stato_display()) for p in progetti]}
