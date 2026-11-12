"""Le chiamate delle istanze dei clienti: autenticate dal loro token, non da una sessione."""
import datetime
import json

from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import servizi
from .models import Istanza, ModuloVendibile, Pacchetto


def _istanza(request):
    intestazione = request.headers.get("Authorization", "")
    return Istanza.per_token(intestazione[7:].strip()) if intestazione.startswith("Bearer ") else None


@csrf_exempt
@require_POST
def sincronizza(request):
    """L'istanza riferisce com'è messa e riceve licenza e catalogo firmati per lei."""
    istanza = _istanza(request)
    if istanza is None:
        return JsonResponse({"errore": "token non valido"}, status=401)
    try:
        dati = json.loads(request.body or b"{}")
        if not isinstance(dati, dict):
            raise ValueError
    except ValueError:
        return JsonResponse({"errore": "corpo non valido"}, status=400)
    moduli = dati.get("moduli") if isinstance(dati.get("moduli"), dict) else {}
    utenti_attivi = dati.get("utenti_attivi") if isinstance(dati.get("utenti_attivi"), int) else None
    istanza.registra_contatto(moduli, utenti_attivi)
    richieste = dati.get("richieste") if isinstance(dati.get("richieste"), list) else []
    ricevute = servizi.ricevi_richieste(istanza, [r for r in richieste if isinstance(r, dict)])
    try:
        file_licenza = servizi.licenza_di(istanza)
        catalogo, firma_catalogo = servizi.catalogo_di(istanza, request.build_absolute_uri("/").rstrip("/"))
    except servizi.ChiaveMancante as e:
        return JsonResponse({"errore": str(e)}, status=503)
    return JsonResponse({**file_licenza, "catalogo": catalogo, "firma_catalogo": firma_catalogo, "ricevute": ricevute,
                         "rifiutate": servizi.rifiutate(istanza), "suite_rifiutate": servizi.rifiutate(istanza, servizi.Richiesta.SUITE)})


@csrf_exempt
@require_POST
def consumi_ai(request):
    """L'istanza riferisce i consumi dell'assistente del mese in corso e del precedente (ai.consumi_portale)."""
    istanza = _istanza(request)
    if istanza is None:
        return JsonResponse({"errore": "token non valido"}, status=401)
    try:
        dati = json.loads(request.body or b"{}")
        mesi = dati["mesi"] if isinstance(dati, dict) and isinstance(dati.get("mesi"), list) else None
    except ValueError:
        mesi = None
    if mesi is None:
        return JsonResponse({"errore": "corpo non valido"}, status=400)
    return JsonResponse({"registrati": servizi.ricevi_consumi_ai(istanza, mesi[:12])})


@require_GET
def pacchetto(request, slug, versione):
    """Il pacchetto si scarica solo se la licenza dell'istanza lo copre e non è scaduta oltre la grazia."""
    istanza = _istanza(request)
    if istanza is None:
        return HttpResponse("token non valido", status=401, content_type="text/plain; charset=utf-8")
    limite = istanza.scadenza + datetime.timedelta(days=istanza.grazia_giorni)
    if slug not in servizi.moduli_di(istanza) or timezone.localdate() > limite:
        return HttpResponse("modulo non coperto dalla licenza", status=403, content_type="text/plain; charset=utf-8")
    p = Pacchetto.objects.filter(modulo__in=ModuloVendibile.objects.filter(slug=slug), versione=versione, pubblicato=True).first()
    if p is None:
        return HttpResponse("pacchetto inesistente", status=404, content_type="text/plain; charset=utf-8")
    return FileResponse(p.file.open("rb"), as_attachment=True, filename=p.nome_file, content_type="application/zip")
