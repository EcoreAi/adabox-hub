"""La pagina dell'impostazione del servizio, solo per il Global Admin, e «Aggiorna» delle previsioni salvate."""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core import lavori
from core.viste import ModelView, register

from . import calcolo, esaurimenti, mie, pagine, pronte, servizio
from .forms import ServizioForm
from .models import EtichettaPrevisione, PrevisioneArticolo, ServizioPrevisioni, StatoCalcolo

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
def pagina(request):
    """La pagina «Previsioni»: una sezione per app, con le previsioni pronte e gli articoli in esaurimento."""
    if not pagine.puo_vedere_la_pagina(request.user):
        raise PermissionDenied
    return render(request, "previsioni/pagina.html", pagine.contesto_pagina(request))


@login_required
def pronta(request, chiave):
    """La card di una previsione pronta, che la pagina e la dashboard caricano con HTMX. 404 se la chiave non esiste o
    l'utente non la può vedere."""
    if chiave not in {p["chiave"] for p in pronte.per_request(request)}:
        raise Http404
    return render(request, "previsioni/_pronta.html", pagine.contesto_pronta(request, chiave))


@login_required
def prodotto_vendite(request, pk):
    """La riga «Vendite previste» della scheda di un prodotto, caricata con HTMX. 404 se l'utente non vede
    `vendite.prodotti`."""
    if not pagine.vendite_prodotti_visibili(request):
        raise Http404
    return render(request, "previsioni/_prodotto_vendite.html", pagine.vendite_prodotto(request, pk))


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
    return redirect("previsioni:pagina")


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

    def has_view_permission(self, request, obj=None):
        """Anche Magazzino, acceso per l'azienda e con il permesso delle giacenze (vale per lista, pagina, riquadro e
        Ada, che passano tutti da qui)."""
        return super().has_view_permission(request, obj) and pagine.magazzino_visibile(request)

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


# ---------- Le mie previsioni ----------

def _mia_previsione(request, origine, pk):
    """La previsione dell'utente su cui agire (rinomina, etichetta). 403 se non vede la pagina, 404 se non è sua."""
    if not pagine.puo_vedere_la_pagina(request.user):
        raise PermissionDenied
    obj = mie.oggetto(origine, pk, request)
    if obj is None:
        raise Http404
    return obj


def _risposta_riga(request, origine, obj):
    """La riga aggiornata per HTMX, altrimenti di nuovo la pagina."""
    if request.headers.get("HX-Request"):
        return render(request, "previsioni/_mia_riga.html", mie.riga(origine, obj, request))
    return redirect("previsioni:pagina")


@login_required
@require_POST
def rinomina(request, origine, pk):
    """Cambia il titolo della previsione d'origine (Artifact o Grafico): il nome nuovo si vede anche in chat e in Analisi."""
    obj = _mia_previsione(request, origine, pk)
    titolo = " ".join(request.POST.get("titolo", "").split())
    if not titolo or len(titolo) > mie.LUNGHEZZA_TITOLO:
        return HttpResponseBadRequest(f"Il titolo non può essere vuoto né più lungo di {mie.LUNGHEZZA_TITOLO} caratteri.")
    obj.titolo = titolo
    # `auto_now` (Grafico.modificato) non scatta con update_fields: lo si aggiunge a mano
    campi = ["titolo"] + (["modificato"] if hasattr(obj, "modificato") else [])
    obj.save(update_fields=campi)
    return _risposta_riga(request, origine, obj)


@login_required
@require_POST
def etichetta(request, origine, pk):
    """Imposta o cambia l'etichetta della previsione; vuota la toglie."""
    obj = _mia_previsione(request, origine, pk)
    testo = " ".join(request.POST.get("etichetta", "").split())
    if len(testo) > mie.LUNGHEZZA_ETICHETTA:
        return HttpResponseBadRequest(f"L'etichetta non può superare {mie.LUNGHEZZA_ETICHETTA} caratteri.")
    chiave = {"utente": request.user, "origine": origine, "oggetto_pk": obj.pk}
    if testo:
        EtichettaPrevisione.objects.update_or_create(**chiave, defaults={"etichetta": testo, "azienda": request.azienda})
    else:
        EtichettaPrevisione.objects.filter(**chiave).delete()
    return _risposta_riga(request, origine, obj)
