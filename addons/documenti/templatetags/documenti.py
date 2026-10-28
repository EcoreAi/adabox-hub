from django import template

from documenti import accesso
from documenti.models import Documento

register = template.Library()


@register.simple_tag(takes_context=True)
def documenti_del_record(context, obj):
    """I documenti (visibili all'utente) collegati a un record qualsiasi."""
    request = context.get("request")
    if request is None or isinstance(obj, Documento) or not request.user.has_perm("documenti.view_documento"):
        return []
    from core.generici import ct_di
    return list(accesso.documenti(request.user, request.azienda).filter(
        content_type=ct_di(obj), object_id=obj.pk, cestinato_il__isnull=True)[:50])
