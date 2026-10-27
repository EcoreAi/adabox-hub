from django.contrib import messages
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import azienda as az
from . import moduli as mod

from .forms import ProfiloForm, TokenApiForm
from .models import Azienda, Modulo, ProfiloUtente, TokenApi
from .registry import modules
from .viste import ModelView, register


def voci_kernel(user):
    """Pagine del kernel nel launcher, secondo i permessi."""
    voci = []
    if user.has_perm("core.view_azienda"):
        voci.append({"label": "Aziende", "url": reverse("core:aziende_lista"), "icon": "tool",
                     "sub": "Anagrafica delle aziende dell'istanza"})
    if user.is_superuser:
        voci.append({"label": "Moduli", "url": reverse("core:moduli"), "icon": "download",
                     "sub": "Installa, aggiorna e disinstalla le app"})
    if user.is_staff:
        voci.append({"label": "Stile", "url": reverse("core:stile"), "icon": "eye",
                     "sub": "Catalogo dei componenti grafici"})
    return voci


@login_required
def home(request):
    try:
        url_moduli = reverse("core:moduli")
    except NoReverseMatch:
        url_moduli = ""
    return render(request, "core/launcher.html", {"kernel": voci_kernel(request.user), "url_moduli": url_moduli})


@login_required
def stile(request):
    return render(request, "core/stile.html")


CHIAVE_TOKEN_NUOVO = "token_api_chiaro"


@login_required
def profilo(request):
    form = ProfiloForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profilo aggiornato.")
        return redirect("core:profilo")
    return render(request, "core/profilo.html", {
        "form": form, "form_token": TokenApiForm(), "token": request.user.token_api.all(),
        "token_chiaro": request.session.pop(CHIAVE_TOKEN_NUOVO, None),   # mostrato una sola volta
    })


@require_POST
@login_required
def token_nuovo(request):
    form = TokenApiForm(request.POST)
    if form.is_valid():
        _, chiaro = TokenApi.genera(request.user, form.cleaned_data["nome"])
        request.session[CHIAVE_TOKEN_NUOVO] = chiaro
        messages.success(request, "Token creato: copialo ora, non sarà più mostrato.")
    else:
        messages.error(request, "Indica un nome per il token.")
    return redirect("core:profilo")


@require_POST
@login_required
def token_revoca(request, pk):
    token = get_object_or_404(TokenApi, pk=pk, utente=request.user)
    token.attivo = False
    token.save(update_fields=["attivo"])
    messages.success(request, f"Token «{token.nome}» revocato.")
    return redirect("core:profilo")


@require_POST
@login_required
def cambia_azienda(request):
    pk = request.POST.get("azienda", "")
    scelta = get_object_or_404(Azienda, pk=int(pk) if pk.isdigit() else 0, attiva=True)
    if scelta not in az.consentite(request.user):
        raise PermissionDenied
    request.session[az.CHIAVE_SESSIONE] = scelta.pk
    messages.success(request, f"Azienda corrente: {scelta}.")
    prossima = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(prossima, {request.get_host()}, request.is_secure()):
        prossima = "/"
    return redirect(prossima)


@register
class AziendaView(ModelView):
    """Gestione delle aziende (/core/aziende/) e banco di prova delle viste generiche."""
    model = Azienda
    slug = "aziende"
    api = True
    api_fields = ["nome", "partita_iva", "codice_fiscale", "citta", "provincia", "email", "telefono", "attiva"]
    list_display = ["nome", "partita_iva", "citta", "attiva"]
    list_filter = ["attiva", "provincia"]
    search_fields = ["nome", "partita_iva"]
    ordering = ["nome"]
    per_page = 25
    form_layout = [
        ("Anagrafica", ["nome", ("partita_iva", "codice_fiscale"), ("indirizzo", "cap"), ("citta", "provincia")]),
        ("Contatti", [("email", "telefono"), "logo", "attiva"]),
    ]
    actions = ["disattiva"]
    buttons = ["attiva"]

    def col_citta(self, obj):
        return obj.citta.upper() if obj.citta else "—"
    col_citta.short_description = "Città"

    def disattiva(self, request, queryset):
        n = queryset.update(attiva=False)
        return f"Aziende disattivate: {n}."
    disattiva.short_description = "Disattiva"

    def attiva(self, request, obj):
        obj.attiva = True
        obj.save(update_fields=["attiva"])
        return f"Azienda «{obj}» attivata."
    attiva.short_description = "Attiva"


def solo_superuser(vista):
    """Login richiesto; poi 403 (non un altro redirect al login) per chi non è superuser."""
    @login_required
    @wraps(vista)
    def interna(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return interna


def _schede_moduli():
    righe = modules.sincronizza()
    info = modules.scopri()
    installati = modules.installati()
    schede = []
    for r in righe:
        m = info[r.slug].manifest if r.slug in info else None
        installato = r.slug in installati
        ops = {
            Modulo.DISPONIBILE: ["installa"],
            Modulo.INSTALLATO: ["disinstalla"],
            Modulo.DA_AGGIORNARE: ["aggiorna", "disinstalla"],
            Modulo.MANCANTE: ["disinstalla"],
            Modulo.ERRORE: ["aggiorna", "disinstalla"] if installato else (["installa"] if m else []),
        }[r.stato]
        schede.append({"riga": r, "manifest": m, "ops": ops})
    return schede


def _pagina_moduli(request, log=None):
    ctx = {"schede": _schede_moduli()}
    if log:
        ctx["log"], (ctx["coda"], ctx["stato"]) = log, mod.leggi(log)
    return render(request, "core/moduli.html", ctx)


@require_GET
@solo_superuser
def moduli(request):
    return _pagina_moduli(request)


@require_POST
@solo_superuser
def moduli_azione(request):
    op, slug = request.POST.get("op", ""), request.POST.get("slug", "")
    if op not in ("installa", "aggiorna", "disinstalla"):
        return HttpResponseBadRequest("operazione sconosciuta")
    if slug not in set(modules.scopri()) | set(modules.installati()):
        return HttpResponseBadRequest("modulo sconosciuto")
    log = mod.avvia(op, slug, demo=request.POST.get("demo") == "1",
                    elimina_dati=request.POST.get("elimina_dati") == "1")
    if not request.headers.get("HX-Request"):
        return _pagina_moduli(request, log)
    coda, stato = mod.leggi(log)
    return render(request, "core/partials/_moduli_stato.html", {"log": log, "coda": coda, "stato": stato})


@require_GET
@solo_superuser
def moduli_stato(request):
    log = request.GET.get("log", "")
    try:
        coda, stato = mod.leggi(log)
    except ValueError:
        return HttpResponseBadRequest("log non valido")
    return render(request, "core/partials/_moduli_stato.html", {"log": log, "coda": coda, "stato": stato})


@register
class ProfiloUtenteView(ModelView):
    """Profili utente: viste generiche senza API e fuori dai menu (si gestiscono anche dall'admin)."""
    model = ProfiloUtente
    slug = "profili"
    list_display = ["utente", "azienda_predefinita"]
    api = False
