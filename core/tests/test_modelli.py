import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models as dj_models

from core import models
from core.mixins import AziendaMixin
from core.models import Azienda, Modulo, TokenApi


@pytest.mark.django_db
def test_azienda_iniziale_dalla_migrazione():
    assert Azienda.objects.get(pk=1).nome == settings.THEME["brand"]


@pytest.mark.django_db
def test_nuovo_utente_ha_il_profilo_con_le_aziende_attive():
    Azienda.objects.create(nome="Beta Srl")
    Azienda.objects.create(nome="Spenta Srl", attiva=False)
    u = User.objects.create_user("anna", "a@example.com", "pass12345!")
    attive = set(Azienda.objects.filter(attiva=True))
    assert set(u.profilo.aziende.all()) == attive
    assert u.profilo.azienda_predefinita == Azienda.objects.filter(attiva=True).order_by("nome").first()


@pytest.mark.django_db
def test_token_genera_e_verifica(utente):
    token, chiaro = TokenApi.genera(utente, "cli")
    assert token.chiave != chiaro
    assert TokenApi.verifica(chiaro) == token
    token.refresh_from_db()
    assert token.ultimo_uso is not None
    assert TokenApi.verifica("x") is None
    token.attivo = False
    token.save()
    assert TokenApi.verifica(chiaro) is None


def test_stati_del_modulo():
    assert [s for s, _ in Modulo.STATI] == ["disponibile", "installato", "da_aggiornare", "mancante", "errore"]


def test_azienda_mixin_astratto():
    assert AziendaMixin._meta.abstract
    campo = AziendaMixin._meta.get_field("azienda")
    assert campo.remote_field.on_delete is dj_models.PROTECT


def test_cliente_rimosso():
    assert hasattr(models, "Cliente") is False
