from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import azienda as az

from .forms import ProfiloForm
from .models import Azienda
from .viste import ModelView, register


def voci_kernel(user):
    """Pagine del kernel nel launcher, secondo i permessi."""
    voci = []
    if user.has_perm("core.view_azienda"):
        voci.append({"label": "Aziende", "url": reverse("core:aziende_lista"), "icon": "tool",
                     "sub": "Anagrafica delle aziende dell'istanza"})
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


@login_required
def profilo(request):
    form = ProfiloForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profilo aggiornato.")
        return redirect("core:profilo")
    return render(request, "core/profilo.html", {"form": form})


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
