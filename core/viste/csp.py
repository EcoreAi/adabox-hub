"""Le segnalazioni della Content-Security-Policy in sola segnalazione (core.middleware.IntestazioniSicurezzaMiddleware).

Il browser manda qui ciò che la politica bloccherebbe; finisce nel log «sicurezza.csp», una riga per violazione
diversa all'ora. Chi scrive qui non è autenticato (lo fa il browser, senza cookie né token): per questo niente
database, corpo corto, e un tetto al minuto, così nessuno può riempire il log."""
import hashlib
import json
import logging
from urllib.parse import urlsplit

from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

log = logging.getLogger("sicurezza.csp")
MASSIMO_CORPO = 16_000
AL_MINUTO = 60
UNA_VOLTA_OGNI = 3600


def _senza_parametri(indirizzo):
    """L'indirizzo senza query né frammento: lì possono esserci dati (token, ricerche)."""
    parti = urlsplit(str(indirizzo or ""))
    return f"{parti.scheme}://{parti.netloc}{parti.path}"[:200] if parti.netloc else str(indirizzo or "")[:200]


@csrf_exempt
@require_POST
def segnalazione(request):
    corpo = request.body[:MASSIMO_CORPO + 1]
    if len(corpo) > MASSIMO_CORPO:
        return HttpResponse(status=413)
    try:
        dati = json.loads(corpo.decode("utf-8", "replace"))
    except ValueError:
        return HttpResponse(status=400)
    voce = dati.get("csp-report") if isinstance(dati, dict) else None
    if not isinstance(voce, dict):
        return HttpResponse(status=400)
    direttiva = str(voce.get("effective-directive") or voce.get("violated-directive") or "")[:80]
    bloccato, pagina = _senza_parametri(voce.get("blocked-uri")), _senza_parametri(voce.get("document-uri"))
    sorgente = _senza_parametri(voce.get("source-file"))
    impronta = hashlib.sha1(f"{direttiva}|{bloccato}|{urlsplit(pagina).path}|{sorgente}".encode()).hexdigest()
    cache.add("csp-al-minuto", 0, 60)
    try:
        troppe = cache.incr("csp-al-minuto") > AL_MINUTO
    except ValueError:
        troppe = False
    if not troppe and cache.add(f"csp:{impronta}", 1, UNA_VOLTA_OGNI):
        log.warning("CSP (sola segnalazione): %s bloccherebbe %s nella pagina %s%s", direttiva or "?", bloccato or "inline",
                    pagina or "?", f" (da {sorgente}, riga {voce.get('line-number')})" if sorgente else "")
    return HttpResponse(status=204)
