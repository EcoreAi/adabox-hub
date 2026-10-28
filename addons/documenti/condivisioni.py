"""Pagina pubblica di una condivisione: niente login, solo i documenti condivisi, accessi registrati e limitati."""
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from core import allegati

from . import servizi
from .models import AccessoCondivisione, Condivisione, Documento

RICHIESTE_AL_MINUTO = 60


def _ip(request):
    return request.META.get("REMOTE_ADDR")


def _troppe(request):
    chiave = f"documenti:condivisi:{_ip(request)}"
    try:
        n = cache.incr(chiave)
    except ValueError:
        cache.set(chiave, 1, 60)
        n = 1
    return n > RICHIESTE_AL_MINUTO


def documenti_di(condivisione):
    qs = Documento.objects.filter(cestinato_il__isnull=True, azienda=condivisione.azienda)
    if condivisione.cartella_id:
        return (qs.filter(cartella=condivisione.cartella) | qs.filter(condivisioni=condivisione)).distinct()
    return qs.filter(condivisioni=condivisione)


def _condivisione(request, token):
    if _troppe(request):
        risposta = HttpResponse("Troppe richieste: riprova tra un minuto.", status=429, content_type="text/plain")
        risposta["Retry-After"] = "60"
        return None, risposta
    condivisione = Condivisione.objects.filter(token=token).first()
    if condivisione is None:
        raise Http404
    if not condivisione.attiva:
        return None, render(request, "documenti/condivisione_scaduta.html", status=410)
    return condivisione, None


def _registra(request, condivisione, azione, documento=None):
    AccessoCondivisione.objects.create(condivisione=condivisione, ip=_ip(request), azione=azione, documento=documento)


@never_cache
@csrf_protect
def pagina(request, token):
    condivisione, errore = _condivisione(request, token)
    if errore:
        return errore
    messaggio = ""
    if request.method == "POST":
        if not (condivisione.consente_caricamento and condivisione.cartella_id):
            raise Http404
        caricati, errori = 0, []
        for file in request.FILES.getlist("file")[:20]:
            try:
                d = servizi.carica(condivisione.cartella, file, None,
                                   descrizione=f"Caricato dal link «{condivisione.nome}»")
                _registra(request, condivisione, "caricamento", d)
                caricati += 1
            except allegati.AllegatoNonValido as e:
                errori.append(str(e))
        messaggio = f"File ricevuti: {caricati}." + (" " + " ".join(errori) if errori else "")
    else:
        _registra(request, condivisione, "visita")
    return render(request, "documenti/condivisione.html", {
        "condivisione": condivisione, "documenti": documenti_di(condivisione), "messaggio": messaggio,
        "caricamento": condivisione.consente_caricamento and condivisione.cartella_id})


@never_cache
def scarica(request, token, pk):
    condivisione, errore = _condivisione(request, token)
    if errore:
        return errore
    documento = get_object_or_404(documenti_di(condivisione), pk=pk)
    _registra(request, condivisione, "download", documento)
    return servizi.risposta(documento, in_linea=False)

