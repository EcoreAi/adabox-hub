"""Hook di installazione di To-Do (chiamati da manage.py modulo)."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    """Tutti gli utenti attivi nel gruppo Utente: dopo l'installazione l'app è subito usabile."""
    gruppo = Group.objects.get(name="To-Do / Utente")
    gruppo.user_set.add(*User.objects.filter(is_active=True))
