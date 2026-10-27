"""Hook di installazione del Calendario."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    Group.objects.get(name="Calendario / Utente").user_set.add(*User.objects.filter(is_active=True))
