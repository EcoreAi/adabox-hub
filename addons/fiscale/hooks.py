"""Hook di installazione delle Impostazioni fiscali."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    Group.objects.get(name="Fiscale / Lettura").user_set.add(*User.objects.filter(is_active=True))
