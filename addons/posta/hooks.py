"""Hook di installazione: ogni utente può collegare la propria casella."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    Group.objects.get(name="Posta e calendario / Utente").user_set.add(*User.objects.filter(is_active=True))
