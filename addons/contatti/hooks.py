"""Hook di installazione di Contatti."""
from django.contrib.auth.models import Group, User

from core import sequenze


def post_install(modulo):
    """Gruppo Utente a tutti gli utenti attivi; codici ai contatti che non lo hanno (dati demo)."""
    from .models import Contatto
    Group.objects.get(name="Contatti / Utente").user_set.add(*User.objects.filter(is_active=True))
    for c in Contatto.objects.filter(codice="").order_by("pk"):
        c.codice = sequenze.prossimo("contatti.contatto", c.azienda)
        c.save(update_fields=["codice"])
