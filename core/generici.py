"""Record generici (content type + pk) e controllo dei permessi tramite la ModelView del modello."""
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import Http404

from core.viste import registry


def ct_di(obj_o_modello):
    return ContentType.objects.get_for_model(obj_o_modello)


def modello_di(ct_id):
    try:
        modello = ContentType.objects.get_for_id(int(ct_id)).model_class()
    except (ContentType.DoesNotExist, ValueError, TypeError):
        raise Http404
    if modello is None:
        raise Http404
    return modello


def vista_e_oggetto(request, ct_id, pk, permesso="view"):
    """(vista, obj) se il modello ha una ModelView, il record è visibile (azienda corrente compresa)
    e l'utente ha il permesso dato su di esso. 404 altrimenti, 403 se manca solo il permesso."""
    vista = registry.per_modello(modello_di(ct_id))
    if vista is None:
        raise Http404
    obj = vista.get_object(request, pk)
    controllo = {"view": vista.has_view_permission, "change": vista.has_change_permission,
                 "delete": vista.has_delete_permission}[permesso]
    if not vista.has_view_permission(request, obj) or not controllo(request, obj):
        raise PermissionDenied
    return vista, obj


def url_record(obj):
    """URL del dettaglio di un record, se il suo modello ha una ModelView montata; altrimenti None."""
    vista = registry.per_modello(type(obj))
    if vista is None:
        return None
    try:
        return vista.url("dettaglio", pk=obj.pk)
    except Exception:
        return None
