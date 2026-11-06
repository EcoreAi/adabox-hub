"""Invito e sospensione dell'accesso al portale, dalla scheda del contatto."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core import modelli_email
from core.models import ProfiloUtente

from .models import AccessoPortale


def link_password(utente):
    uid = urlsafe_base64_encode(force_bytes(utente.pk))
    return settings.SITO_URL + reverse("password_reset_confirm", args=[uid, default_token_generator.make_token(utente)])


def invita(contatto, da_utente):
    """Crea (o riattiva) l'utente esterno del contatto e gli manda il link per scegliere la password."""
    if not contatto.email:
        raise ValueError("Il contatto non ha un indirizzo email.")
    Utente = get_user_model()
    accesso = AccessoPortale.objects.filter(contatto=contatto).select_related("utente").first()
    if accesso is None:
        if Utente.objects.filter(username__iexact=contatto.email).exists():
            raise ValueError(f"Esiste già un utente {contatto.email}: non può diventare un accesso al portale.")
        utente = Utente.objects.create_user(contatto.email.lower(), contatto.email, get_random_string(32),
                                            first_name=contatto.nome[:150])
        ProfiloUtente.objects.update_or_create(utente=utente, defaults={"esterno": True})
        accesso = AccessoPortale.objects.create(utente=utente, contatto=contatto, invitato_da=da_utente)
    utente = accesso.utente
    if not utente.is_active:
        utente.is_active = True
        utente.save(update_fields=["is_active"])
    modelli_email.messaggio("portale.invito", contatto.azienda, {
        "nome": contatto.nome, "cliente": accesso.cliente, "link_password": link_password(utente),
        "link_accesso": f"{settings.SITO_URL}{reverse('login')}", "nome_utente": utente.username}, [contatto.email]).send()
    return accesso


def sospendi(accesso):
    accesso.utente.is_active = False
    accesso.utente.save(update_fields=["is_active"])
