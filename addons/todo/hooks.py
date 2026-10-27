"""Hook di installazione di To-Do (chiamati da manage.py modulo)."""
from django.contrib.auth.models import Group, User

from core import sequenze


def numera(queryset):
    """Assegna il numero di sequenza alle attività che non lo hanno, in ordine di creazione."""
    for a in queryset.filter(numero="").order_by("creato", "pk"):
        a.numero = sequenze.prossimo("todo.attivita", a.azienda)
        a.save(update_fields=["numero"])


def post_install(modulo):
    """Tutti gli utenti attivi nel gruppo Utente (l'app è subito usabile); numeri ai dati demo."""
    from .models import Attivita
    gruppo = Group.objects.get(name="To-Do / Utente")
    gruppo.user_set.add(*User.objects.filter(is_active=True))
    numera(Attivita.objects.all())


def post_upgrade(modulo, da_versione):
    """1.0 -> 1.1: le attività esistenti ricevono il numero."""
    from .models import Attivita
    if da_versione.startswith("1.0."):
        numera(Attivita.objects.all())
