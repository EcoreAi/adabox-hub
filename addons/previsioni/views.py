"""La pagina dell'impostazione del servizio, solo per il Global Admin, e «Aggiorna» delle previsioni salvate."""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core import lavori
from core.viste import ModelView, register

from . import calcolo, esaurimenti, servizio
from .forms import ServizioForm
from .models import PrevisioneArticolo, ServizioPrevisioni, StatoCalcolo

ENTRO = ("7", "30", "90")           # i giorni di «entro N giorni»
PERMESSI_AGGIORNA = {StatoCalcolo.MAGAZZINO: "previsioni.change_previsionearticolo",
                     StatoCalcolo.VENDITE: "previsioni.change_previsionepronta"}


@login_required
def pagina_servizio(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    corrente = ServizioPrevisioni.corrente()
    form = ServizioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.salva(corrente)
        messages.success(request, "Impostazione del servizio di previsione salvata.")
        return redirect("previsioni:servizio")
    return render(request, "previsioni/servizio.html", {
        "form": form, "chiave_impostata": bool(corrente.chiave_cifrata), "url_servizio": servizio.url()})


@login_required
@require_POST
def aggiorna(request):
    """«Aggiorna» (`?cosa=magazzino` o `vendite`, ognuna col suo permesso): il ricalcolo va in un lavoro in background,
    perché ogni chiamata al servizio può durare minuti, e si torna alla pagina di prima."""
    cosa, azienda = request.GET.get("cosa", ""), getattr(request, "azienda", None)
    if cosa not in calcolo.CALCOLI or azienda is None:
        return HttpResponseBadRequest("Previsioni da aggiornare sconosciute o nessuna azienda corrente.")
    if not request.user.has_perm(PERMESSI_AGGIORNA[cosa]):
        raise PermissionDenied
    if not calcolo.eseguibile(cosa, azienda):
        return HttpResponseBadRequest("Queste previsioni non si calcolano per l'azienda corrente.")
    lavori.accoda("previsioni.calcolo.aggiorna", azienda=azienda, utente=request.user, max_tentativi=1,
                  azienda_id=azienda.pk, cosa=cosa)
    messages.success(request, "Aggiornamento avviato: le previsioni saranno pronte tra poco.")
    indietro = request.META.get("HTTP_REFERER", "")
    if url_has_allowed_host_and_scheme(indietro, {request.get_host()}, request.is_secure()):
        return redirect(indietro)
    return redirect("core:home")


@register
class ArticoliInEsaurimentoView(ModelView):
    """Le previsioni di magazzino salvate, dalla prima a finire: solo da leggere, le ricalcola il modulo."""
    model = PrevisioneArticolo
    slug = "esaurimenti"
    verbose_name = "articolo in esaurimento"
    verbose_name_plural = "articoli in esaurimento"
    company_field = "azienda"
    storico = False
    list_display = ["prodotto", "magazzino", "partenza", "consumo_mensile", "riordino", "esaurimento", "stato", "affidabilita"]
    list_filter = ["magazzino", "stato"]
    search_fields = ["prodotto", "codice"]
    ai_descrizione = ("Gli articoli di magazzino con la data prevista di esaurimento e di riordino, calcolate ogni notte "
                      "dal modulo Previsioni")
    template_lista = "previsioni/esaurimenti_lista.html"
    template_tabella = "previsioni/_esaurimenti_tabella.html"

    def get_queryset(self, request):
        """Per data di riordino, senza data in fondo; `?entro=N` (7, 30, 90) tiene chi va riordinato entro N giorni."""
        qs = super().get_queryset(request).order_by(F("riordino").asc(nulls_last=True), "pk")
        entro = request.GET.get("entro", "")
        if entro in ENTRO:
            qs = qs.filter(riordino__lte=timezone.localdate() + datetime.timedelta(days=int(entro)))
        return qs

    def col_magazzino(self, obj):
        return obj.magazzino or "Tutti i magazzini"

    def col_esaurimento(self, obj):
        """La data prevista con la fascia 10–90 %: «12/03/2027 (08/03/2027 – 18/04/2027)»."""
        if not obj.esaurimento:
            return "—"
        fascia = esaurimenti.fascia(obj)
        return f"{obj.esaurimento:%d/%m/%Y} ({fascia})" if fascia else f"{obj.esaurimento:%d/%m/%Y}"

    def col_affidabilita(self, obj):
        return str(obj.affidabilita.get("livello", "")).capitalize() or "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
