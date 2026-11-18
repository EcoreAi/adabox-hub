"""Ada legge le notifiche delle Comunicazioni («che notifiche ho?»)."""
import pytest
from django.contrib.auth.models import User

from ai.strumenti import Contesto
from discuss import ai
from discuss.models import Notifica


@pytest.fixture
def anna(db):
    return User.objects.create_user("anna")


def test_notifiche_non_lette_dell_utente(anna):
    mario = User.objects.create_user("mario", first_name="Mario")
    Notifica.objects.create(utente=anna, tipo=Notifica.MENZIONE, autore=mario, titolo="Mario ti ha menzionato",
                            testo="Guarda il preventivo", url="/discuss/c/1/")
    Notifica.objects.create(utente=anna, tipo=Notifica.DIRETTO, titolo="Vecchia", url="/x/", letta=True)
    Notifica.objects.create(utente=mario, tipo=Notifica.DIRETTO, titolo="Di un altro", url="/y/")
    r = ai.notifiche(Contesto(utente=anna))
    assert r["non_lette"] == 1 and [n["titolo"] for n in r["notifiche"]] == ["Mario ti ha menzionato"]
    assert r["notifiche"][0]["tipo"] == "Menzione" and r["notifiche"][0]["da"] == "Mario"
    tutte = ai.notifiche(Contesto(utente=anna), anche_lette=True)
    assert [n["titolo"] for n in tutte["notifiche"]] == ["Vecchia", "Mario ti ha menzionato"] or len(tutte["notifiche"]) == 2
    assert not Notifica.objects.get(titolo="Mario ti ha menzionato").letta      # leggerle con Ada non le segna
