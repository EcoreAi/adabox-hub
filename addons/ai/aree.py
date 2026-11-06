"""Chi vede e chi gestisce un'area di lavoro (ProgettoChat).

- La vede chi l'ha creata e i membri, sempre nella stessa azienda.
- La gestisce solo chi l'ha creata: istruzioni, cartella, app predefinita, record collegati, membri, eliminazione.
- Le chat sono di chi le scrive: gli altri membri vedono solo quelle condivise con l'area, in sola lettura."""
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Conversazione, MembroArea, ProgettoChat


def visibili(utente, azienda):
    if azienda is None:
        return ProgettoChat.objects.none()
    return ProgettoChat.objects.filter(azienda=azienda).filter(Q(utente=utente) | Q(membri__utente=utente)).distinct()


def visibile(utente, azienda, pk):
    """L'area se l'utente la vede, altrimenti None."""
    if not str(pk or "").isdigit():
        return None
    return visibili(utente, azienda).filter(pk=pk).first()


def gestita(utente, azienda, pk):
    """L'area se l'utente l'ha creata (e quindi la gestisce), altrimenti None."""
    if azienda is None or not str(pk or "").isdigit():
        return None
    return ProgettoChat.objects.filter(pk=pk, utente=utente, azienda=azienda).first()


def puo_vedere(utente, area):
    return area is not None and (area.utente_id == utente.pk or area.membri.filter(utente=utente).exists())


def chat_visibili(utente, area):
    """Le chat dell'area che l'utente vede: le sue e quelle condivise dagli altri membri."""
    return Conversazione.objects.filter(progetto=area, nascosta=False).filter(Q(utente=utente) | Q(condivisa=True)).select_related("utente")


def candidati(area_o_azienda, proprietario):
    """Gli utenti attivi della stessa azienda con cui si può condividere (non chi l'ha creata)."""
    azienda = getattr(area_o_azienda, "azienda", area_o_azienda)
    return get_user_model().objects.filter(is_active=True, profilo__aziende=azienda).exclude(pk=proprietario.pk).order_by("first_name", "username")


def imposta_membri(area, utenti):
    """I membri dell'area diventano `utenti`. Chi esce perde l'accesso: le sue chat escono dall'area (restano sue) e le
    sue attività pianificate non lavorano più lì."""
    from .models import Pianificata
    nuovi = {u.pk for u in utenti if u.pk != area.utente_id}
    attuali = set(area.membri.values_list("utente_id", flat=True))
    usciti = attuali - nuovi
    MembroArea.objects.filter(progetto=area, utente_id__in=usciti).delete()
    MembroArea.objects.bulk_create([MembroArea(progetto=area, utente_id=pk) for pk in nuovi - attuali])
    if usciti:
        Conversazione.objects.filter(progetto=area, utente_id__in=usciti).update(progetto=None, condivisa=False)
        Pianificata.objects.filter(progetto=area, utente_id__in=usciti).update(progetto=None)
    return nuovi - attuali, usciti


def nome(utente):
    return utente.get_full_name() or utente.username
