import datetime

import pytest
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.utils import timezone

from core import chatter
from core.models import Azienda
from discuss import notifiche, servizi
from discuss.models import Canale, Iscrizione, Notifica


def _utente(nome, *permessi):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_canale", "add_canale", "add_messaggio",
                                                                  *permessi]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def persone(db):
    return _utente("anna"), _utente("bruno", "view_azienda"), _utente("carla")


def test_menzione_diretto_e_preferenze(persone):
    anna, bruno, carla = persone
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna, [bruno, carla])
    servizi.invia(canale, anna, "nessuna menzione")
    assert not Notifica.objects.exists()                                  # default: solo le menzioni
    Iscrizione.objects.filter(utente=carla).update(notifiche="tutto")
    servizi.invia(canale, anna, "ciao @bruno")
    assert {(n.utente.username, n.tipo) for n in Notifica.objects.all()} == {("bruno", "menzione"), ("carla", "canale")}
    menzione = Notifica.objects.get(utente=bruno)
    assert "ti ha menzionato" in menzione.titolo and menzione.url.endswith(f"#m{canale.messaggi.last().pk}")
    Iscrizione.objects.filter(utente=bruno).update(notifiche="niente")
    servizi.invia(canale, anna, "@bruno ancora")
    assert Notifica.objects.filter(utente=bruno).count() == 1
    diretto = servizi.diretto([anna, carla])
    servizi.invia(diretto, anna, "solo per te")
    assert Notifica.objects.filter(utente=carla, tipo="diretto").exists()
    assert not Notifica.objects.filter(utente=anna).exists()              # mai per i propri messaggi


def test_menzione_di_chi_non_e_nel_canale(persone):
    anna, bruno, carla = persone
    pubblico = servizi.crea_canale("pubblico", Canale.PUBBLICO, anna)
    privato = servizi.crea_canale("privato", Canale.PRIVATO, anna)
    servizi.invia(pubblico, anna, "@carla guarda")
    servizi.invia(privato, anna, "@carla segreto")
    assert list(Notifica.objects.values_list("utente__username", "messaggio__canale__nome")) == [("carla", "pubblico")]


def test_chatter_menzioni_e_follower(persone):
    anna, bruno, carla = persone
    azienda = Azienda.objects.get(pk=1)
    chatter.segui(azienda, carla)
    chatter.scrivi(azienda, anna, "Nota per @bruno e @carla", tipo="nota")
    assert list(Notifica.objects.values_list("utente__username", "tipo")) == [("bruno", "menzione")]  # carla non vede le aziende
    chatter.scrivi(azienda, anna, "Messaggio ai follower")
    n = Notifica.objects.get(utente=carla)
    assert n.tipo == "record" and n.url == f"/core/aziende/{azienda.pk}/" and "Messaggio ai follower" in n.testo
    chatter.scrivi(azienda, anna, "tracciamento", tipo="tracciamento")
    assert Notifica.objects.count() == 2


def test_posta_in_arrivo(client, persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna, [bruno])
    servizi.invia(canale, anna, "@bruno leggi")
    client.force_login(bruno)
    html = client.get("/discuss/posta/").content.decode()
    assert "Anna ti ha menzionato" in html and "is-nuova" in html
    n = Notifica.objects.get()
    r = client.get(f"/discuss/notifica/{n.pk}/")
    assert r.url.startswith(f"/discuss/c/{canale.pk}/") and Notifica.objects.get().letta
    servizi.invia(canale, anna, "@bruno ancora")
    client.post("/discuss/posta/lette/")
    assert not Notifica.objects.filter(letta=False).exists()
    client.force_login(anna)
    assert client.get(f"/discuss/notifica/{n.pk}/").status_code == 404


def test_aprire_il_canale_segna_lette(client, persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna, [bruno])
    servizi.invia(canale, anna, "@bruno uno")
    client.force_login(bruno)
    client.get(f"/discuss/c/{canale.pk}/")
    assert not Notifica.objects.filter(letta=False).exists()


def test_campanella_in_testata(client, persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna, [bruno])
    servizi.invia(canale, anna, "@bruno ciao")
    client.force_login(bruno)
    html = client.get("/dashboard/").content.decode()
    assert 'id="ds-campanella"' in html and "1 non letti" in html
    r = client.get("/discuss/contatore/").content.decode()
    assert 'hx-trigger="every 30s"' in r


def test_email_dei_non_letti(persone, settings):
    anna, bruno, carla = persone
    settings.SITO_URL = "https://hub.example.com"
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna, [bruno, carla])
    servizi.invia(canale, anna, "@bruno @carla urgente")
    assert notifiche.invia_email() == "email inviate: 0"                   # troppo presto
    Notifica.objects.update(creata=timezone.now() - datetime.timedelta(minutes=20))
    Notifica.objects.filter(utente=carla).update(letta=True)
    assert notifiche.invia_email() == "email inviate: 1"
    email = mail.outbox[-1]
    assert email.to == ["bruno@example.com"] and "urgente" in email.body and "https://hub.example.com/discuss/" in email.body
    assert notifiche.invia_email() == "email inviate: 0"                   # una volta sola
