"""Hook di installazione dell'Assistente AI."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    from . import catalogo
    Group.objects.get(name="AI / Utente").user_set.add(*User.objects.filter(is_active=True))
    catalogo.crea_iniziali()


def post_upgrade(modulo, da_versione):
    from . import catalogo
    from .models import Profilo
    catalogo.crea_iniziali()
    # 1.2: le attività pianificate scrivono riepiloghi interi, non titoli
    Profilo.objects.filter(compito="pianificate", max_token=1024).update(max_token=16000)
