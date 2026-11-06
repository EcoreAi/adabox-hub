"""Le chat di un contatto: solo quelle in cui chi guarda è dentro."""
from django import template

from discuss.models import ConversazioneEsterna

register = template.Library()


@register.simple_tag(takes_context=True)
def chat_del_contatto(context, contatto):
    utente = context["request"].user
    return list(ConversazioneEsterna.objects.filter(contatto_pk=contatto.pk, canale__membri=utente)
                .select_related("canale", "sportello").order_by("-pk")[:20])
