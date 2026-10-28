"""Hook di installazione dell'Assistente AI."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    Group.objects.get(name="AI / Utente").user_set.add(*User.objects.filter(is_active=True))
