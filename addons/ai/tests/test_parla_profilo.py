"""«Parla con Ada» usa il profilo «voce» se l'amministratore l'ha creato; il turno conta comunque come chat."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from ai import motore
from ai.gateway import esecuzione
from ai.models import AnelloCatena, Conversazione, Modello, Profilo, Provider


@pytest.fixture
def scena(db, monkeypatch, settings):
    settings.AI_TURNI_SINCRONI = True
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)

    def modello(id_api):
        return Modello.objects.create(provider=provider, id_api=id_api, etichetta=id_api, prezzo_input=Decimal(1), prezzo_output=Decimal(1))
    lento, veloce = modello("finto-lento"), modello("finto-veloce")
    for compito in ("chat", "titoli"):
        AnelloCatena.objects.create(profilo=Profilo.objects.create(nome=compito, compito=compito), modello=lento, ordine=1)
    utente = User.objects.create_user("anna", password="x")
    return {"utente": utente, "veloce": veloce, "lento": lento, "c": Conversazione.objects.create(utente=utente, titolo="x")}


def test_senza_profilo_voce_vale_quello_della_chat(scena):
    turno = motore.avvia(scena["c"], "ciao", scena["utente"], voce=True)
    turno.refresh_from_db()
    assert turno.voce and turno.compito == "chat" and turno.modello == scena["lento"]


def test_con_il_profilo_voce_si_usa_il_suo_modello(scena):
    p = Profilo.objects.create(nome="Parla con Ada", compito="voce", max_token=1500)
    AnelloCatena.objects.create(profilo=p, modello=scena["veloce"], ordine=1)
    a_voce = motore.avvia(scena["c"], "ciao", scena["utente"], voce=True)
    a_voce.refresh_from_db()
    assert a_voce.modello == scena["veloce"] and a_voce.compito == "chat"            # conta come chat (licenza, cruscotto)
    scritta = motore.avvia(Conversazione.objects.create(utente=scena["utente"], titolo="y"), "ciao", scena["utente"])
    scritta.refresh_from_db()
    assert scritta.modello == scena["lento"]                                          # la chat scritta non cambia


def test_a_voce_solo_gli_strumenti_utili_al_telefono(scena):
    from ai import parla
    from ai.gateway import finto
    User.objects.filter(pk=scena["utente"].pk).update(is_superuser=True)
    utente = User.objects.get(pk=scena["utente"].pk)
    with finto.con_copione([["ok"], ["Titolo"], ["ok"], ["Titolo"]]) as chiamate:
        motore.avvia(scena["c"], "ciao", utente, voce=True)
        a_voce = set(chiamate[0]["strumenti"])
        motore.avvia(Conversazione.objects.create(utente=utente, titolo="y"), "ciao", utente)
        scritta = set(chiamate[2]["strumenti"])
    assert a_voce and a_voce <= parla.STRUMENTI_VOCE and len(scritta) > len(a_voce)
    assert "elimina_record" in scritta and "elimina_record" not in a_voce and "grafico" not in a_voce
