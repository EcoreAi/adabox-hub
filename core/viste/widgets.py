"""Resa in sola lettura dei valori dei campi (lista e dettaglio)."""
import datetime

from django.core.exceptions import FieldDoesNotExist
from django.db.models.fields.files import FieldFile
from django.utils import timezone
from django.utils.html import format_html

VUOTO = "—"


def _link(vista_rel, request, valore):
    if vista_rel is None or request is None or not vista_rel.has_view_permission(request, valore):
        return None
    try:
        return format_html('<a class="ui-link" href="{}">{}</a>', vista_rel.url("dettaglio", pk=valore.pk), valore)
    except Exception:          # vista registrata ma non montata negli URL
        return None


def rendi(vista, obj, campo, request=None):
    from . import registry
    if campo == "__str__":
        return str(obj)
    try:
        f = vista.opts.get_field(campo)
    except FieldDoesNotExist:
        f = None
    if f is not None and f.many_to_many:
        valori = list(getattr(obj, campo).all())
        return ", ".join(str(v) for v in valori) or VUOTO
    if f is not None and f.choices:
        return getattr(obj, f"get_{campo}_display")() or VUOTO
    valore = getattr(obj, campo, None)
    if f is None and callable(valore):
        valore = valore()
    if isinstance(valore, FieldFile):
        valore = valore.name.rsplit("/", 1)[-1] if valore else ""           # il nome, non il percorso interno
    if valore is None or valore == "":
        return VUOTO
    if isinstance(valore, bool):
        if valore:
            return format_html('<span class="ui-pill ui-pill-ok">{}</span>', "Sì")
        return format_html('<span class="ui-pill ui-pill-neutral">{}</span>', "No")
    if isinstance(valore, datetime.datetime):
        return timezone.localtime(valore).strftime("%d/%m/%Y %H:%M") if timezone.is_aware(valore) \
            else valore.strftime("%d/%m/%Y %H:%M")
    if isinstance(valore, datetime.date):
        return valore.strftime("%d/%m/%Y")
    if f is not None and f.is_relation:
        return _link(registry.per_modello(type(valore)), request, valore) or str(valore)
    return valore
