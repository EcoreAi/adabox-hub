"""Hook di installazione delle Impostazioni fiscali."""
import json
from pathlib import Path

from django.contrib.auth.models import Group, User


def post_upgrade(modulo, da_versione):
    """Le aliquote nuove arrivano anche agli impianti esistenti; quelle già presenti non si toccano."""
    from .models import AliquotaIva
    for voce in json.loads((Path(__file__).parent / "data" / "iniziali.json").read_text()):
        if voce["model"].endswith("aliquotaiva"):
            campi = dict(voce["fields"])
            AliquotaIva.objects.get_or_create(codice=campi.pop("codice"), defaults=campi)


def post_install(modulo):
    Group.objects.get(name="Fiscale / Lettura").user_set.add(*User.objects.filter(is_active=True))
