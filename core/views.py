from django.contrib import messages
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.migrations.recorder import MigrationRecorder
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import azienda as az
from . import moduli as mod
from . import attivita as attivita_servizio
from . import parametri

from .forms import AziendaPredefinitaForm, CampoPersonalizzatoForm, ProfiloForm, TokenApiForm
from .models import Azienda, CampoPersonalizzato, EmailRicevuta, Lavoro, Modulo, ProfiloUtente, TokenApi
from .registry import modules
from .signals import crea_profilo
from .viste import ModelView, register


def voci_kernel(user):
    """Pagine del kernel nel launcher, secondo i permessi."""
    voci = []
    if attivita_servizio.mie(user).exists():
        voci.append({"label": "Le mie attività", "url": reverse("core:attivita"), "icon": "check",
                     "sub": f"Da fare oggi o scadute: {attivita_servizio.da_fare_oggi(user)}"})
    if user.has_perm("core.view_azienda"):
        voci.append({"label": "Aziende", "url": reverse("core:aziende_lista"), "icon": "tool",
                     "sub": "Anagrafica delle aziende dell'istanza"})
    if user.is_superuser:
        voci.append({"label": "Lavori", "url": reverse("core:lavoro_lista"), "icon": "zap",
                     "sub": "Coda dei lavori in background"})
        voci.append({"label": "Email ricevute", "url": reverse("core:email_lista"), "icon": "inbox",
                     "sub": "Risposte alle notifiche e loro abbinamento"})
        voci.append({"label": "Moduli", "url": reverse("core:moduli"), "icon": "download",
                     "sub": "Installa, aggiorna e disinstalla le app"})
    if user.has_perm("core.view_campopersonalizzato"):
        voci.append({"label": "Campi personalizzati", "url": reverse("core:campi_lista"), "icon": "edit",
                     "sub": "Campi aggiunti ai modelli senza programmare"})
    if user.has_perm("core.change_parametro") and parametri.definizioni():
        voci.append({"label": "Impostazioni", "url": reverse("core:impostazioni"), "icon": "tool",
                     "sub": "Parametri delle app installate"})
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
    form_azienda = None
    if len(az.consentite(request.user)) > 1:
        form_azienda = AziendaPredefinitaForm(instance=crea_profilo(request.user))
    return render(request, "core/profilo.html", {
        "form": form, "form_azienda": form_azienda,
        "form_token": TokenApiForm(), "token": request.user.token_api.all(),
        "token_chiaro": request.session.pop(CHIAVE_TOKEN_NUOVO, None),   # mostrato una sola volta
    })


@require_POST
@login_required
def azienda_predefinita(request):
    form = AziendaPredefinitaForm(request.POST, instance=crea_profilo(request.user))
    if form.is_valid():
        form.save()
        messages.success(request, f"Azienda predefinita: {form.instance.azienda_predefinita}.")
    else:
        messages.error(request, "Azienda non consentita.")
    return redirect("core:profilo")


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
    chatter = True
    tracked_fields = ["nome", "partita_iva", "attiva"]
    reports = [{"nome": "Scheda azienda", "template": "core/report/azienda.html"}]

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
    # migrazioni ancora registrate = tabelle rimaste (disinstallato senza --elimina-dati)
    con_dati = set(MigrationRecorder.Migration.objects.values_list("app", flat=True).distinct())
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
        schede.append({"riga": r, "manifest": m, "ops": ops,
                       "dati_presenti": not installato and r.slug in con_dati})
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


class SoloSuperuserView(ModelView):
    """Viste del kernel in sola lettura per il superuser (lavori, email ricevute, ...)."""

    def _perm(self, request, azione):
        return azione == "view" and request.user.is_superuser


@register
class LavoroView(SoloSuperuserView):
    model = Lavoro
    list_display = ["funzione", "stato", "tentativi", "esegui_dopo", "finito"]
    list_filter = ["stato"]
    search_fields = ["funzione"]
    form_layout = [("Lavoro", ["funzione", "argomenti", ("stato", "tentativi", "max_tentativi")]),
                   ("Tempi", [("creato", "esegui_dopo"), ("iniziato", "finito")]),
                   ("Esito", ["risultato", "errore"])]
    readonly_fields = ["creato"]
    buttons = ["riprova"]

    def col_errore(self, obj):
        return format_html('<pre class="ui-log">{}</pre>', obj.errore) if obj.errore else "—"
    col_errore.short_description = "Errore"

    def riprova(self, request, obj):
        from . import lavori
        lavori.riprova(obj)
        return "Lavoro rimesso in coda."
    riprova.short_description = "Riprova"
    riprova.permission = "view"


@login_required
def impostazioni(request):
    """Una card per modulo con `settings` nel manifest; si salva un modulo alla volta."""
    if not request.user.has_perm("core.change_parametro"):
        raise PermissionDenied
    azienda = getattr(request, "azienda", None)
    manifest = modules.manifests_attivi()
    moduli_con = [slug for slug, m in manifest.items() if m.settings]
    inviato = request.POST.get("modulo") if request.method == "POST" else None
    if inviato is not None and inviato not in moduli_con:
        return HttpResponseBadRequest("modulo sconosciuto")
    schede = []
    for slug in moduli_con:
        form = parametri.ImpostazioniForm(slug, azienda, request.POST if inviato == slug else None)
        if inviato == slug and form.is_valid():
            form.salva()
            messages.success(request, f"Impostazioni di {manifest[slug].name} salvate.")
            return redirect(f"{reverse('core:impostazioni')}#{slug}")
        schede.append({"slug": slug, "nome": manifest[slug].name, "form": form})
    return render(request, "core/impostazioni.html", {"schede": schede})


@register
class EmailRicevutaView(SoloSuperuserView):
    model = EmailRicevuta
    slug = "email"
    list_display = ["oggetto", "mittente", "stato", "ricevuta"]
    list_filter = ["stato"]
    search_fields = ["oggetto", "mittente", "message_id"]
    form_layout = [("Email", ["oggetto", ("mittente", "ricevuta"), "message_id"]),
                   ("Esito", [("stato", "messaggio"), "motivo"])]
    readonly_fields = ["ricevuta"]


@login_required
def attivita_mie(request):
    return render(request, "core/attivita_mie.html", {"gruppi": attivita_servizio.raggruppate(request.user)})


@register
class CampoPersonalizzatoView(ModelView):
    model = CampoPersonalizzato
    slug = "campi"
    list_display = ["label", "nome", "modello", "tipo", "azienda", "in_lista", "filtrabile"]
    list_filter = ["modello", "tipo", "azienda"]
    search_fields = ["label", "nome"]
    ordering = ["modello", "ordine", "pk"]
    form_class = CampoPersonalizzatoForm
    form_layout = [("Campo", ["modello", ("label", "nome"), ("tipo", "ordine"), "scelte", "aiuto"]),
                   ("Comportamento", [("obbligatorio", "in_lista", "filtrabile"), "azienda"])]
