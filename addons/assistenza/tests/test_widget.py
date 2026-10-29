import json
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.staticfiles import finders
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from assistenza import widget
from assistenza.models import DatiTicket, Supporto
from contatti.models import Contatto
from core.models import Allegato, Azienda
from helpdesk.models import Team, Ticket
from progetti.models import Progetto

SITO = "https://app.rossi.it"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def scena(db, settings, tmp_path):
    import helpdesk
    call_command("loaddata", str(Path(helpdesk.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    azienda = Azienda.objects.get(pk=1)
    sara = User.objects.create_user("sara", "sara@example.com", "x")
    team = Team.objects.create(nome="Sviluppo")
    team.membri.add(sara)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    progetto = Progetto.objects.create(azienda=azienda, nome="Gestionale Rossi", cliente=cliente)
    supporto = Supporto.objects.create(azienda=azienda, progetto=progetto, team=team, responsabile=sara,
                                       domini=f"{SITO}/\nhttps://staging.rossi.it")
    return {"supporto": supporto, "cliente": cliente, "sara": sara, "team": team}


def _invia(client, chiave, origine=SITO, **campi):
    dati = {"oggetto": "Il salvataggio non va", "descrizione": "Premo Salva e niente", "email": "anna@rossi.it",
            "nome": "Anna Rossi", "tipo": "bug", "tecnici": json.dumps({"pagina": f"{SITO}/ordini/12",
                                                                       "browser": "Firefox", "versione": "2.3.1",
                                                                       "inventato": "x"}), **campi}
    return client.post(f"/assistenza/widget/{chiave}/", dati, HTTP_ORIGIN=origine)


def test_preflight_e_siti_non_ammessi(client, scena):
    url = f"/assistenza/widget/{scena['supporto'].chiave}/"
    r = client.options(url, HTTP_ORIGIN=SITO)
    assert r.status_code == 204 and r["Access-Control-Allow-Origin"] == SITO
    r = _invia(client, scena["supporto"].chiave, origine="https://cattivo.example")
    assert r.status_code == 403 and "Access-Control-Allow-Origin" not in r
    assert _invia(client, "chiave-inventata").status_code == 404
    Supporto.objects.filter(pk=scena["supporto"].pk).update(domini="")
    assert _invia(client, scena["supporto"].chiave).status_code == 404                    # senza siti: spento
    assert not Ticket.objects.exists()


def test_segnalazione_completa(client, scena):
    r = _invia(client, scena["supporto"].chiave, screenshot=SimpleUploadedFile("s.png", PNG, "image/png"))
    risposta = r.json()
    ticket = Ticket.objects.get()
    assert r.status_code == 200 and risposta == {"ok": True, "numero": ticket.numero}
    assert r["Access-Control-Allow-Origin"] == SITO
    dati = DatiTicket.objects.get(ticket=ticket)
    assert dati.canale == "widget" and dati.tipo == "bug" and dati.progetto == scena["supporto"].progetto
    assert dati.tecnici["pagina"] == f"{SITO}/ordini/12" and dati.tecnici["versione"] == "2.3.1"
    assert "inventato" not in dati.tecnici and dati.tecnici["ip"]
    assert ticket.team == scena["team"] and ticket.assegnatario == scena["sara"]
    anna = ticket.contatto
    assert anna.email == "anna@rossi.it" and anna.societa == scena["cliente"] and anna.tipo == "persona"
    assert Allegato.objects.filter(content_type=ContentType.objects.get_for_model(Ticket), object_id=ticket.pk).exists()
    assert mail.outbox[-1].to == ["anna@rossi.it"] and ticket.numero in mail.outbox[-1].subject
    _invia(client, scena["supporto"].chiave, oggetto="Un altro")
    assert Contatto.objects.filter(email="anna@rossi.it").count() == 1                    # stesso contatto


def test_campo_esca_ed_errori(client, scena):
    chiave = scena["supporto"].chiave
    r = _invia(client, chiave, sito_web="http://spam.example")
    assert r.json()["ok"] and not Ticket.objects.exists()                                # il bot crede di esserci riuscito
    assert "email valido" in _invia(client, chiave, email="").json()["errore"]
    assert "oggetto" in _invia(client, chiave, oggetto=" ").json()["errore"]
    r = _invia(client, chiave, screenshot=SimpleUploadedFile("x.exe", b"MZ", "application/octet-stream"))
    assert r.status_code == 400 and "immagine" in r.json()["errore"]
    assert not Ticket.objects.exists()


def test_limite_di_frequenza(client, scena, monkeypatch):
    monkeypatch.setattr(widget, "LIMITE_ORA", 2)
    chiave = scena["supporto"].chiave
    assert [_invia(client, chiave).status_code for _ in range(3)] == [200, 200, 429]


def test_script_e_istruzioni_nella_scheda(client, scena):
    assert finders.find("assistenza/widget.js")
    client.force_login(User.objects.create_superuser("root", "r@example.com", "x"))
    html = client.get(f"/assistenza/supporto/{scena['supporto'].pk}/").content.decode()
    assert f'data-chiave="{scena["supporto"].chiave}"' in html and "assistenza/widget.js" in html
