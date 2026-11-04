"""Il ricalcolo periodico dei grafici salvati: il worker del kernel accoda `aggiorna_scaduti` (voce `cron` del
manifest) e ogni grafico con «aggiorna ogni N ore» che ha superato la scadenza si ricalcola con i permessi e
l'azienda predefinita del proprietario, come se lo aprisse lui."""
import datetime
import logging

from django.utils import timezone

from core.viste import interroga
from core.viste.interroga import ErroreInterrogazione

from . import motore
from .models import Grafico

log = logging.getLogger("grafici.lavori")
MAX_PER_GIRO = 200


def scaduti(adesso=None):
    adesso = adesso or timezone.now()
    return [g for g in Grafico.objects.filter(aggiorna_ogni__gt=0).select_related("utente").order_by("aggiornato", "pk")
            if g.aggiornato is None or g.aggiornato + datetime.timedelta(hours=g.aggiorna_ogni) <= adesso][:MAX_PER_GIRO]


def aggiorna_scaduti():
    """Quanti grafici sono stati ricalcolati. Un grafico che non si può calcolare (permessi cambiati, servizio giù)
    tiene i dati di prima e riprova alla prossima scadenza."""
    adesso = timezone.now()
    fatti = 0
    for g in scaduti(adesso):
        if not g.utente.is_active:
            continue
        request = interroga.richiesta_di(g.utente)
        try:
            g.dati = motore.dati_di(g.tipo, g.spec, request)
            fatti += 1
        except ErroreInterrogazione as e:
            log.info("grafico %s di %s non ricalcolato: %s", g.pk, g.utente, e)
        except Exception:                                   # un grafico rotto non ferma gli altri
            log.exception("grafico %s di %s", g.pk, g.utente)
        g.aggiornato = adesso
        g.save(update_fields=["dati", "aggiornato"])
    return fatti
