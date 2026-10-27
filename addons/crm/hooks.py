"""Hook di installazione del CRM."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    Group.objects.get(name="CRM / Commerciale").user_set.add(*User.objects.filter(is_active=True))
