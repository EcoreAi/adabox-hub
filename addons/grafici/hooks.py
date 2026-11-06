"""Hook di installazione di Analisi."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    Group.objects.get(name="Analisi / Utente").user_set.add(*User.objects.filter(is_active=True))
