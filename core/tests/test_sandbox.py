"""INT-08: l'istanza di prova per chi integra. Il comando rifiuta un'istanza vera; in sandbox crea utente e token, il
banner c'è su ogni pagina e lo SDI passa dal simulatore."""
import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import TokenApi


@pytest.mark.django_db
def test_rifiuta_un_istanza_vera(settings):
    settings.SANDBOX = False
    with pytest.raises(CommandError, match="non è un'istanza di prova"):
        call_command("sandbox", "prepara")


@pytest.mark.django_db
def test_prepara_utente_token_e_banner(settings, client, monkeypatch):
    settings.SANDBOX = True
    chiamate = []
    from django.core import management
    vero = management.call_command

    def finto(nome, *args, **kw):                             # i dati demo hanno i loro test: qui basta sapere che parte
        if nome == "dati_demo":
            chiamate.append(args)
            return None
        return vero(nome, *args, **kw)
    monkeypatch.setattr("core.management.commands.sandbox.call_command", finto)
    uscita = io.StringIO()
    call_command("sandbox", "prepara", "--giorni", "30", stdout=uscita)
    testo = uscita.getvalue()
    assert chiamate == [("genera",)] and "Token API" in testo and "/api/v1/sdk/python/" in testo
    t = TokenApi.objects.get(utente__username="integrazione")
    assert t.scadenza is not None and t.utente.profilo.ruolo.nome == "Integrazione"
    chiaro = testo.split("): ", 1)[1].split()[0]
    assert client.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Bearer {chiaro}").json()["username"] == "integrazione"
    assert "Ambiente di prova" in client.get("/accounts/login/").content.decode()


def test_in_sandbox_lo_sdi_va_al_simulatore(settings):
    from django.apps import apps
    if not apps.is_installed("sdi"):
        pytest.skip("sdi non installato")
    from sdi import canali
    settings.SANDBOX = True
    assert isinstance(canali.per_azienda(None), canali.Prova)
