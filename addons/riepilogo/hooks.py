"""Hook di installazione del Riepilogo."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    Group.objects.get(name="Riepilogo / Utente").user_set.add(*User.objects.filter(is_active=True, profilo__esterno=False))
    Group.objects.get(name="Riepilogo / Utente").user_set.add(*User.objects.filter(is_active=True, profilo__isnull=True))
