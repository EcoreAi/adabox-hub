import pytest
from django.contrib.auth.models import Permission, User
from django.test import Client
from django.urls import reverse

from discuss import assegnazioni, assistente_sito, ia, presenza, servizi
from discuss.models import ConversazioneEsterna, Notifica, Sportello


def _utente(nome):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_canale", "add_messaggio"]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(db):
    x = Sportello.objects.create(nome="Assistenza", distribuzione=Sportello.TUTTI)
    x.operatori.add(_utente("olga"), _utente("piero"))
    return x


def _op(s, nome):
    return s.operatori.get(username=nome)


def _avvia(s, ip="1.1.1.1", testo="Aiuto"):
    t = Client(REMOTE_ADDR=ip).post(reverse("discuss:lc_avvia", args=[s.chiave]), {"nome": "Mario", "testo": testo}).json()["token"]
    return ConversazioneEsterna.objects.select_related("canale", "sportello").get(token=t)


def _assegna(client, c, valore):
    return client.post(reverse("discuss:lc_assegna", args=[c.canale_id]), {"utente": valore})


def test_tutti_avvisati_finche_qualcuno_non_la_prende(client, s):
    olga, piero = _op(s, "olga"), _op(s, "piero")
    c = _avvia(s)
    assert Notifica.objects.filter(utente=olga).count() == 1 and Notifica.objects.filter(utente=piero).count() == 1
    client.force_login(olga)
    html = client.get(f"/discuss/c/{c.canale_id}/").content.decode()
    assert "Da prendere in carico" in html and "Prendi in carico" in html
    assert _assegna(client, c, olga.pk).status_code == 302
    c.refresh_from_db()
    assert c.assegnata_a == olga and c.canale.messaggi.filter(tipo="sistema", corpo__contains="ha preso in carico").exists()
    assert not Notifica.objects.filter(utente=olga, titolo__contains="assegnata").exists()      # l'ha presa da sola
    # d'ora in poi i messaggi del cliente avvisano solo lei
    Notifica.objects.all().delete()
    Client().post(reverse("discuss:lc_scrivi", args=[s.chiave]), {"testo": "Ci sei?"}, headers={"X-Token": c.token})
    assert Notifica.objects.filter(utente=olga).count() == 1 and not Notifica.objects.filter(utente=piero).exists()
    # nella barra di ciascuno sta nel posto giusto
    assert "Le mie" in client.get("/discuss/posta/").content.decode()
    client.force_login(piero)
    html = client.get("/discuss/posta/").content.decode()
    assert "Dei colleghi (1)" in html and "di Olga" in html


def test_chi_risponde_la_prende_e_non_la_toglie_a_chi_ce_l_ha(s):
    olga, piero = _op(s, "olga"), _op(s, "piero")
    c = _avvia(s)
    servizi.invia(c.canale, piero, "Eccomi")
    c.refresh_from_db()
    assert c.assegnata_a == piero
    servizi.invia(c.canale, olga, "Aggiungo una cosa")
    c.refresh_from_db()
    assert c.assegnata_a == piero


def test_assegnare_a_un_collega_e_lasciare(client, s):
    olga, piero = _op(s, "olga"), _op(s, "piero")
    c = _avvia(s)
    client.force_login(olga)
    Notifica.objects.all().delete()
    _assegna(client, c, piero.pk)
    c.refresh_from_db()
    assert c.assegnata_a == piero and Notifica.objects.get(utente=piero, titolo__contains="Ti è stata assegnata")
    assert c.canale.messaggi.filter(corpo__contains="ha assegnato la chat a Piero").exists()
    _assegna(client, c, "0")
    c.refresh_from_db()
    assert c.assegnata_a is None


def test_non_si_assegna_a_chi_non_e_operatore_ne_da_fuori(client, s):
    olga = _op(s, "olga")
    estraneo = _utente("ugo")
    c = _avvia(s)
    client.force_login(olga)
    assert _assegna(client, c, estraneo.pk).status_code == 403
    c.refresh_from_db()
    assert c.assegnata_a is None
    client.force_login(estraneo)
    assert _assegna(client, c, estraneo.pk).status_code == 404
    assert Client().post(reverse("discuss:lc_assegna", args=[c.canale_id]), {"utente": "1"}).status_code == 302   # al login


def test_a_turno_all_operatore_collegato_con_meno_chat(s):
    Sportello.objects.filter(pk=s.pk).update(distribuzione=Sportello.A_TURNO)
    s.refresh_from_db()
    olga, piero = _op(s, "olga"), _op(s, "piero")
    # nessuno collegato: resta da prendere e sono avvisati tutti
    c0 = _avvia(s, ip="9.9.9.9")
    c0.refresh_from_db()
    assert c0.assegnata_a is None and Notifica.objects.filter(utente=piero).exists() and Notifica.objects.filter(utente=olga).exists()
    presenza.tocca(olga)
    presenza.tocca(piero)
    c1, c2, c3 = _avvia(s, ip="1.1.1.1"), _avvia(s, ip="2.2.2.2"), _avvia(s, ip="3.3.3.3")
    for c in (c1, c2, c3):
        c.refresh_from_db()
    assert [c.assegnata_a for c in (c1, c2, c3)] == [olga, piero, olga]
    # solo l'incaricato è avvisato
    assert Notifica.objects.filter(titolo__contains="Ti è stata assegnata", utente=olga).count() == 2
    # chi ha chiesto di non essere disturbato non ne riceve; chi si è scollegato nemmeno
    presenza.mia(olga).__class__.objects.filter(utente=olga).update(stato="occupato")
    c4 = _avvia(s, ip="4.4.4.4")
    c4.refresh_from_db()
    assert c4.assegnata_a == piero


def test_dall_ai_a_turno_avvisa_solo_chi_la_riceve(s, monkeypatch):
    monkeypatch.setattr(ia, "genera", lambda *a, **k: assistente_sito.MARCATORE)
    monkeypatch.setattr("ai.conoscenza.embedding", lambda testi, tipo="document": None)
    Sportello.objects.filter(pk=s.pk).update(distribuzione=Sportello.A_TURNO, modalita=Sportello.AI)
    s.refresh_from_db()
    olga, piero = _op(s, "olga"), _op(s, "piero")
    presenza.tocca(piero)
    c = _avvia(s)
    c.refresh_from_db()
    assert c.gestita_da == "persona" and c.assegnata_a == piero
    assert not Notifica.objects.filter(utente=olga).exists() and Notifica.objects.filter(utente=piero, titolo__contains="ha bisogno").exists()
