"""Hook di installazione delle Commesse."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    Group.objects.get(name="Commesse / Utente").user_set.add(*User.objects.filter(is_active=True))
