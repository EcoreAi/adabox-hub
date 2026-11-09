"""I contratti di lavoro: quello in vigore porta orario, ferie e permessi sul dipendente (su cui contano saldi e
presenze), le scadenze vicine si segnalano."""
import datetime

from django.db.models import Q
from django.utils import timezone

from .models import ContrattoLavoro, Dipendente

CAMPI = {"ore_settimanali": "ore_settimanali", "giorni_ferie_annui": "giorni_ferie_annui", "ore_permesso_annue": "ore_permesso_annue",
         "tipo": "tipo_contratto"}
GIORNI_AVVISO = 30


def in_vigore(dipendente, data=None):
    data = data or timezone.localdate()
    return (ContrattoLavoro.objects.filter(dipendente=dipendente, dal__lte=data).filter(Q(al__isnull=True) | Q(al__gte=data))
            .order_by("-dal").first())


def allinea(dipendente, data=None):
    """Copia sul dipendente i dati del contratto in vigore. Restituisce True se qualcosa è cambiato."""
    c = in_vigore(dipendente, data)
    if c is None:
        return False
    cambi = {d: getattr(c, s) for s, d in CAMPI.items() if getattr(dipendente, d) != getattr(c, s)}
    if not cambi:
        return False
    Dipendente.objects.filter(pk=dipendente.pk).update(**cambi)
    for k, v in cambi.items():
        setattr(dipendente, k, v)
    return True


def contratto_salvato(sender, instance, **kwargs):
    allinea(instance.dipendente)


def giro():
    """Ogni giorno: i contratti che iniziano oggi diventano quelli del dipendente."""
    oggi = timezone.localdate()
    n = 0
    for d in Dipendente.objects.filter(contratti__dal=oggi).distinct():
        n += allinea(d, oggi)
    return n


def in_scadenza(qs, oggi=None):
    """I contratti che finiscono entro GIORNI_AVVISO senza un contratto successivo: da rinnovare o da chiudere."""
    oggi = oggi or timezone.localdate()
    limite = oggi + datetime.timedelta(days=GIORNI_AVVISO)
    risultato = []
    for c in qs.filter(al__gte=oggi, al__lte=limite).select_related("dipendente").order_by("al"):
        if not ContrattoLavoro.objects.filter(dipendente=c.dipendente, dal__gt=c.al).exists():
            risultato.append(c)
    return risultato
