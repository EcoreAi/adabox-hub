"""Hook di installazione dei Progetti."""
from django.contrib.auth.models import Group, User

from core import sequenze


def post_install(modulo):
    from .models import Progetto
    Group.objects.get(name="Progetti / Utente").user_set.add(*User.objects.filter(is_active=True))
    for p in Progetto.objects.filter(codice="").order_by("pk"):
        p.codice = sequenze.prossimo("progetti.progetto", p.azienda)
        p.save(update_fields=["codice"])
