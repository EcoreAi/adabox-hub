from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def approvazioni_record(context, obj):
    """Le richieste di approvazione del record, con chi può decidere ora: per la sezione nel dettaglio."""
    from core import approvazioni
    request = context.get("request")
    if obj is None or getattr(obj, "pk", None) is None or request is None:
        return []
    voci = []
    for r in approvazioni.richieste_di(obj).select_related("catena", "richiesta_da").prefetch_related("decisioni__utente")[:5]:
        puo, per_conto = approvazioni.puo_decidere(r, request.user)
        voci.append({"r": r, "puo": puo, "per_conto": per_conto, "passi": r.catena.passi.count()})
    return voci
