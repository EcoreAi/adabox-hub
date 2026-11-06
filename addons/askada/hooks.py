"""Hook di installazione di Chiedi ad Ada."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    Group.objects.get(name="Chiedi ad Ada / Utente").user_set.add(*User.objects.filter(is_active=True))
