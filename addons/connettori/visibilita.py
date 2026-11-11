"""Chi vede i record arrivati da un collegamento «ogni utente con la sua chiave».

Un record di Odoo esiste una volta sola in adabox (RiferimentoEsterno), ma lo vede solo chi, con la sua chiave, lo
vede in Odoo (VisibilitaEsterna, allineata a ogni giro). I record nati in adabox seguono le regole di sempre. Il
filtro vale per ogni vista, come le regole sui ruoli: liste, API, esportazioni, assistente, portale. Chi ha il
permesso «Vede anche i dati esterni che il sistema mostra ad altri utenti» li vede tutti."""
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from .models import CollegamentoEsterno, RiferimentoEsterno, VisibilitaEsterna

# i record «di qualcuno» che arrivano per utente; i prodotti sono un catalogo comune e restano fuori dal filtro
PER_UTENTE = {"contatti.contatto", "crm.opportunita", "calendario.evento", "vendite.ordinevendita"}


def _sistemi_per_utente(request, azienda_id):
    """I sistemi dell'azienda con un collegamento per utente attivo (una volta per richiesta)."""
    cache = getattr(request, "_connettori_per_utente", None)
    if cache is None or cache[0] != azienda_id:
        sistemi = list(CollegamentoEsterno.objects.filter(azienda_id=azienda_id, attivo=True, per_utente=True).values_list("sistema", flat=True))
        cache = (azienda_id, sistemi)
        try:
            request._connettori_per_utente = cache
        except AttributeError:                            # richieste finte senza attributi liberi
            pass
    return cache[1]


def filtro(vista, request, qs):
    """Registrato in core.regole: toglie i record esterni che l'utente non vede nel sistema da cui arrivano."""
    azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
    utente = getattr(request, "user", None)
    if azienda_id is None or utente is None or not getattr(utente, "is_authenticated", False) or vista.opts.label_lower not in PER_UTENTE:
        return qs
    sistemi = _sistemi_per_utente(request, azienda_id)
    if not sistemi or utente.has_perm("connettori.vede_tutti_i_dati_esterni"):
        return qs
    rif = RiferimentoEsterno.objects.filter(azienda_id=azienda_id, sistema__in=sistemi, content_type=ContentType.objects.get_for_model(vista.model))
    if not rif.exists():
        return qs
    visibili = VisibilitaEsterna.objects.filter(riferimento__in=rif, account__utente=utente, account__collegamento__sistema__in=sistemi)
    return qs.exclude(Q(pk__in=rif.values("object_id")) & ~Q(pk__in=visibili.values("riferimento__object_id")))


def gestito_da(obj):
    """Registrata in core.esterni: un ordine di vendita arrivato da un sistema esterno resta di quel sistema (sola
    lettura, niente consegne né fatture da adabox)."""
    if obj._meta.label_lower != "vendite.ordinevendita":
        return None
    rif = RiferimentoEsterno.objects.filter(azienda_id=obj.azienda_id, content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk).first()
    if rif is None:
        return None
    return dict(CollegamentoEsterno.SISTEMI).get(rif.sistema, rif.sistema)
