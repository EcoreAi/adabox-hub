"""Hook di installazione di Discuss."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    """Tutti gli utenti nel gruppo base e nel canale «generale»."""
    from . import servizi
    from .models import Canale
    utenti = list(User.objects.filter(is_active=True))
    Group.objects.get(name="Discuss / Utente").user_set.add(*utenti)
    generale = Canale.objects.filter(nome="generale", tipo=Canale.PUBBLICO).first()
    if generale is None and utenti:
        generale = servizi.crea_canale("generale", Canale.PUBBLICO, utenti[0], utenti,
                                       "Comunicazioni per tutti")
    elif generale is not None:
        for u in utenti:
            servizi.iscrivi(generale, u)


def demo(modulo):
    from . import servizi
    from .models import Canale
    autore = User.objects.filter(is_superuser=True).order_by("pk").first()
    generale = Canale.objects.filter(nome="generale").first()
    if autore is None or generale is None or generale.messaggi.exists():
        return
    servizi.invia(generale, autore, "Benvenuti su **Discuss**! Qui scriviamo le comunicazioni per tutti.")
    servizi.invia(generale, autore, "Per parlare con un collega usate i messaggi diretti, a sinistra.")
    commerciale = servizi.crea_canale("commerciale", Canale.PUBBLICO, autore, descrizione="Offerte, clienti, fiere")
    servizi.invia(commerciale, autore, "Ricordate di aggiornare le opportunità nel CRM entro venerdì.")
