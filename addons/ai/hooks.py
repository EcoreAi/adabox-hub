"""Hook di installazione dell'Assistente AI."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    from . import catalogo
    Group.objects.get(name="AI / Utente").user_set.add(*User.objects.filter(is_active=True))
    catalogo.crea_iniziali()


def post_upgrade(modulo, da_versione):
    from . import catalogo
    catalogo.crea_iniziali()
