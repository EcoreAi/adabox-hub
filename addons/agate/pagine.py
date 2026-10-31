"""Pagine del modulo, montate sotto /agate/: collegamento, valutazioni, webhook di Agate."""
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core import cifratura

from . import cliente
from .guardia import decisa
from .models import Collegamento, Valutazione

log = logging.getLogger("agate.pagine")


def _salva(request, collegamento):
    collegamento.gateway_url = request.POST.get("gateway_url", "").strip()
    collegamento.console_url = request.POST.get("console_url", "").strip()
    collegamento.prefisso = request.POST.get("prefisso", "").strip() or "adabox"
    collegamento.modalita = request.POST.get("modalita", Collegamento.OSSERVAZIONE)
    if chiave := request.POST.get("chiave", "").strip():
        collegamento.imposta_chiave(chiave)
    if segreto := request.POST.get("segreto", "").strip():
        collegamento.imposta_segreto(segreto)
    collegamento.full_clean(exclude=["chiave_cifrata", "segreto_cifrato"])
    collegamento.save()


def _prova(collegamento):
    try:
        nomi = [m.get("id") for m in cliente.modelli(collegamento)]
        collegamento.esito_controllo = f"Agate risponde: modelli {', '.join(n for n in nomi if n) or 'nessuno'}"
    except cliente.ErroreAgate as e:
        collegamento.esito_controllo = f"Agate non accetta: {e}"[:300]
    collegamento.ultimo_controllo = timezone.now()
    collegamento.save(update_fields=["esito_controllo", "ultimo_controllo"])
    return collegamento.esito_controllo


def usa_agate_per_i_modelli(collegamento):
    """Un provider «Agate» compatibile OpenAI (`/v1/llm`) con i modelli scelti dall'azienda in Agate: le
    chiavi dei fornitori restano in Agate, i dati personali vengono mascherati lì, il costo si conta lì."""
    from ai.models import Modello, Provider

    nomi = [m.get("id") for m in cliente.modelli(collegamento) if m.get("id")]
    provider, _ = Provider.objects.get_or_create(nome="Agate", defaults={"tipo": Provider.OPENAI_COMPAT})
    provider.tipo = Provider.OPENAI_COMPAT
    provider.base_url = collegamento.gateway_url.rstrip("/") + "/v1/llm"
    provider.chiave_cifrata = collegamento.chiave_cifrata
    provider.locale = False
    provider.attivo = True
    provider.save()
    for nome in nomi:
        Modello.objects.get_or_create(provider=provider, id_api=nome, defaults={"etichetta": f"Agate · {nome}"})
    return provider, nomi


@login_required
@permission_required("agate.change_collegamento", raise_exception=True)
def collegamento(request):
    attuale = Collegamento.attuale()
    if request.method == "POST":
        azione = request.POST.get("azione", "salva")
        try:
            if azione == "salva":
                attuale = attuale or Collegamento()
                _salva(request, attuale)
                messages.success(request, f"Collegamento salvato. {_prova(attuale)}")
            elif azione == "prova" and attuale:
                messages.info(request, _prova(attuale))
            elif azione == "modelli" and attuale:
                provider, nomi = usa_agate_per_i_modelli(attuale)
                messages.success(request, f"Provider «{provider.nome}» pronto con {len(nomi)} modelli: sceglili nei "
                                          "Profili dell'assistente.")
        except cliente.ErroreAgate as e:
            messages.error(request, str(e))
        except Exception as e:                           # validazione del modello
            messages.error(request, f"Dati non validi: {e}")
        return redirect("agate:collegamento")
    return render(request, "agate/collegamento.html", {
        "c": attuale, "modalita": Collegamento.MODALITA,
        "chiave": cifratura.mascherato(attuale.chiave()) if attuale and attuale.chiave_cifrata else "",
        "segreto": bool(attuale and attuale.segreto_cifrato),
        "webhook_url": request.build_absolute_uri("/agate/webhook/"),
        "conteggi": {s: Valutazione.objects.filter(stato=s).count() for s, _ in Valutazione.STATI},
    })


@login_required
@permission_required("agate.view_valutazione", raise_exception=True)
def valutazioni(request):
    righe = Valutazione.objects.select_related("proposta", "utente")[:200]
    c = Collegamento.attuale()
    return render(request, "agate/valutazioni.html", {"righe": righe, "console": c.console_url if c else ""})


@csrf_exempt
@require_POST
def webhook(request):
    """Eventi di Agate firmati col segreto: `approval.decided` esegue o chiude la proposta in attesa."""
    c = Collegamento.attuale()
    if c is None or not c.segreto_cifrato:
        return HttpResponse(status=404)
    try:
        cliente.verifica_firma(c.segreto(), request.headers.get("X-Agate-Signature"), request.body)
        evento = json.loads(request.body)
    except (ValueError, cifratura.SegretoIlleggibile):
        return HttpResponse(status=401)
    if evento.get("type") == "approval.decided":
        dati = evento.get("data") or {}
        valutazione = Valutazione.objects.filter(approval_id=str(dati.get("approval_id", ""))).first()
        if valutazione is not None:
            decisa(valutazione, str(dati.get("decision", "")), motivo=str(dati.get("reason") or ""))
    return JsonResponse({"ricevuto": True})
