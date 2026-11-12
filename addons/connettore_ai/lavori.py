"""Pulizia giornaliera: ciò che è scaduto non serve più a nessuno."""
from datetime import timedelta

from django.utils import timezone

from .models import ClientOAuth, Codice, ChatCollegata, Token

CONSERVA_CHIAMATE = timedelta(days=365)
CLIENT_MAI_USATO = timedelta(days=7)


def pulisci():
    """Codici e token scaduti; collegamenti rimasti senza token di rinnovo (90 giorni senza uso): revocati; client
    registrati da sé e mai usati; chiamate più vecchie di un anno."""
    from .models import Chiamata
    adesso = timezone.now()
    Codice.objects.filter(scade__lt=adesso - timedelta(days=1)).delete()
    Token.objects.filter(scade__lt=adesso).delete()
    spenti = ChatCollegata.objects.filter(revocato__isnull=True, creato__lt=adesso - timedelta(days=1)).exclude(token__tipo=Token.RINNOVO)
    quanti = spenti.update(revocato=adesso)
    ClientOAuth.objects.filter(tipo=ClientOAuth.DCR, creato__lt=adesso - CLIENT_MAI_USATO, collegamenti__isnull=True).delete()
    Chiamata.objects.filter(creato__lt=adesso - CONSERVA_CHIAMATE).delete()
    return f"{quanti} collegamenti scaduti"
