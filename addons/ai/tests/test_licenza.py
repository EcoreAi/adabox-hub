import datetime
import io
import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from ai import licenza, limiti
from ai.gateway import ErroreModello, esecuzione, finto
from ai.models import AnelloCatena, Conversazione, Licenza, Modello, Profilo, Provider, Turno
from core import parametri
from core.models import Azienda
from core.registry import pacchetti

OGGI = timezone.localdate()


@pytest.fixture
def chiavi(settings, tmp_path):
    pem, pub = pacchetti.genera_chiavi()
    settings.MODULI_CHIAVI_FIDATE = [pub]
    settings.AI_LICENZA_SVILUPPO = False
    percorso = tmp_path / "privata.pem"
    percorso.write_bytes(pem)
    return percorso


def _licenza(chiavi, **dati):
    base = {"cliente": "Rossi Srl", "emessa": OGGI.isoformat(),
            "scadenza": (OGGI + datetime.timedelta(days=365)).isoformat(), "utenti": 0, "funzioni": ["chat"]}
    return json.dumps(licenza.firma({**base, **dati}, pacchetti.carica_privata(chiavi)))


def test_licenza_valida_scaduta_manomessa(db, chiavi):
    stato = licenza.leggi(_licenza(chiavi))
    assert stato.valida and stato.cliente == "Rossi Srl" and stato.funzioni == ["chat"]
    scaduta = licenza.leggi(_licenza(chiavi, scadenza=(OGGI - datetime.timedelta(days=1)).isoformat()))
    assert not scaduta.valida and "scaduta" in scaduta.motivo
    manomessa = json.loads(_licenza(chiavi))
    manomessa["licenza"]["utenti"] = 999
    assert "Firma non valida" in licenza.leggi(json.dumps(manomessa)).motivo
    estranea_pem, _ = pacchetti.genera_chiavi()
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    altra = json.dumps(licenza.firma({"cliente": "X", "scadenza": "2099-01-01"}, load_pem_private_key(estranea_pem, None)))
    assert not licenza.leggi(altra).valida
    assert not licenza.leggi("non json").valida
    assert licenza.attuale().motivo == "Nessuna licenza caricata."


def test_senza_licenza_l_assistente_non_risponde(db, chiavi):
    with pytest.raises(ErroreModello, match="non è attivo"):
        limiti.verifica()
    Licenza.objects.create(testo=_licenza(chiavi, funzioni=["chat"]))
    limiti.verifica()
    with pytest.raises(ErroreModello, match="non è compresa"):
        limiti.verifica(funzione="conoscenza")


def test_limite_di_utenti(db, chiavi):
    Licenza.objects.create(testo=_licenza(chiavi, utenti=1))
    anna, bruno = User.objects.create_user("anna"), User.objects.create_user("bruno")
    Turno.objects.create(utente=anna, compito="chat")
    limiti.verifica(utente=anna)                                          # già contata
    with pytest.raises(ErroreModello, match="numero di utenti"):
        limiti.verifica(utente=bruno)


def test_tetto_di_spesa_e_avviso(db, settings):
    azienda = Azienda.objects.get(pk=1)
    admin = User.objects.create_user("admin", email="admin@example.com")
    admin.user_permissions.add(Permission.objects.get(codename="change_provider"))
    parametri.scrivi("ai.tetto_mensile", Decimal("10"), azienda)
    Turno.objects.create(azienda=azienda, costo=Decimal("7"))
    limiti.verifica(azienda)
    assert not mail.outbox
    Turno.objects.create(azienda=azienda, costo=Decimal("1.5"))
    limiti.verifica(azienda)
    limiti.verifica(azienda)
    assert len(mail.outbox) == 1 and "8.50 $ su 10" in mail.outbox[0].subject       # una volta sola al mese
    Turno.objects.create(azienda=azienda, costo=Decimal("2"))
    with pytest.raises(ErroreModello, match="tetto di spesa"):
        limiti.verifica(azienda)
    parametri.scrivi("ai.tetto_mensile", Decimal("0"), azienda)
    limiti.verifica(azienda)                                              # 0 = senza tetto


def test_il_motore_rispetta_il_tetto(db, monkeypatch):
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    azienda = Azienda.objects.get(pk=1)
    p = Provider.objects.create(nome="F", tipo="finto")
    m = Modello.objects.create(provider=p, id_api="f", etichetta="F")
    profilo = Profilo.objects.create(nome="c", compito="chat")
    AnelloCatena.objects.create(profilo=profilo, modello=m)
    utente = User.objects.create_user("u")
    parametri.scrivi("ai.tetto_mensile", Decimal("1"), azienda)
    Turno.objects.create(azienda=azienda, costo=Decimal("1"))
    from ai import motore
    with finto.con_copione([["non arriva"]]) as chiamate:
        turno = motore.avvia(Conversazione.objects.create(utente=utente), "ciao", utente, azienda)
    turno.refresh_from_db()
    assert turno.stato == "errore" and "tetto di spesa" in turno.testo and not chiamate


def test_pagina_licenza_e_comando(client, superuser, chiavi, tmp_path):
    html = client.get("/ai/licenza/").content.decode()
    assert "Nessuna licenza caricata" in html
    uscita = tmp_path / "licenza.json"
    call_command("ai_licenza", "--chiave", str(chiavi), "--cliente", "Bianchi Spa", "--scadenza", "2099-12-31",
                 "--utenti", "5", "--uscita", str(uscita), stdout=io.StringIO())
    r = client.post("/ai/licenza/", {"file": SimpleUploadedFile("licenza.json", uscita.read_bytes())}, follow=True)
    assert "Licenza di Bianchi Spa caricata" in r.content.decode()
    stato = licenza.attuale()
    assert stato.valida and stato.utenti == 5 and "chat" in stato.funzioni
    r = client.post("/ai/licenza/", {"file": SimpleUploadedFile("x.json", b"{}")}, follow=True)
    assert "non caricata" in r.content.decode() and Licenza.objects.count() == 1


def test_chat_mostra_l_avviso_senza_licenza(client, superuser, chiavi):
    assert "L&#x27;assistente non è attivo" in client.get("/ai/chat/").content.decode()


def test_consumi_e_dashboard(client, superuser):
    from ai.dashboard import kpi
    azienda = Azienda.objects.get(pk=1)
    Turno.objects.create(azienda=azienda, utente=superuser, compito="chat", costo=Decimal("0.0123"), stato="completato")
    html = client.get("/ai/consumi/").content.decode()
    assert "0.0123 $" in html
    richiesta = type("R", (), {"user": superuser, "azienda": azienda})()
    valori = {k["etichetta"].split(" su ")[0]: k["valore"] for k in kpi(richiesta)["kpi"]}
    assert valori["spesa AI del mese"] == "0.01 $" and valori["domande all'assistente oggi"] == 1
