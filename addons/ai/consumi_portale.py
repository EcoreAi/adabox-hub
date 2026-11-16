"""I consumi dell'assistente riferiti al portale di chi vende l'istanza: con la formula «a consumo» servono a
fatturare, con quella «inclusa» a controllare il margine.

Parte un riepilogo per mese (quello in corso e il precedente, così l'ultimo giorno non si perde): costo totale, costo
sui provider forniti con il piano, numero di turni e di persone. Nessun nome e nessun testo. Il portale tiene una riga
per mese e la sostituisce: rimandare gli stessi numeri non cambia niente. Chi usa la sua chiave (formula «propria»)
non riferisce niente: quanto spende con il suo fornitore non riguarda chi gli vende adabox."""
import datetime
import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from . import licenza
from .models import Turno

log = logging.getLogger("ai.limiti")
TIMEOUT = 30


def configurato():
    return bool(settings.LICENZA_PORTALE_URL and settings.LICENZA_TOKEN)


def _mesi():
    """Il primo giorno del mese in corso e di quello precedente."""
    questo = timezone.localdate().replace(day=1)
    return [questo, (questo - datetime.timedelta(days=1)).replace(day=1)]


def riepilogo(mese):
    turni = Turno.objects.filter(iniziato__year=mese.year, iniziato__month=mese.month)
    totali = turni.aggregate(costo=Sum("costo"), fornito=Sum("costo_fornito"), turni=Count("pk"))
    return {"mese": f"{mese:%Y-%m}", "costo": f"{totali['costo'] or Decimal(0):.6f}",
            "costo_fornito": f"{totali['fornito'] or Decimal(0):.6f}", "turni": totali["turni"],
            "utenti": turni.filter(compito="chat", utente__isnull=False).values("utente").distinct().count()}


def _chiama(dati):
    richiesta = urllib.request.Request(
        f"{settings.LICENZA_PORTALE_URL.rstrip('/')}/consumi-ai/", data=json.dumps(dati).encode(), method="POST",
        headers={"Authorization": f"Bearer {settings.LICENZA_TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
        return risposta.status


def invia():
    """Voce `cron` del manifest: l'esito in una riga, o None se non c'è un portale o non c'è niente da riferire."""
    if not configurato():
        return None
    propria = licenza.attuale().formula == licenza.PROPRIA
    # con la chiave del cliente partono solo i mesi con un costo sul piano (la formula è appena cambiata)
    mesi = [r for r in map(riepilogo, _mesi()) if not propria or Decimal(r["costo_fornito"])]
    if not mesi:
        return None
    try:
        _chiama({"mesi": mesi})
    except (urllib.error.URLError, OSError) as e:       # si riprova al prossimo giro: i numeri si ricalcolano
        log.warning("consumi dell'assistente non arrivati al portale: %s", e)
        return f"non arrivati al portale: {e}"
    return "inviati: " + ", ".join(m["mese"] for m in mesi)


invia.senza_transazione = True      # una chiamata di rete: non deve tenere aperta una transazione
