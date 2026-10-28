import datetime

import pytest
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.utils import timezone

from core import attivita, chatter
from core.generici import ct_di
from core.models import AttivitaPianificata, Azienda, TipoAttivita

OGGI = timezone.localdate()


def _utente(nome, *codenames):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def scena(db):
    acme = Azienda.objects.create(nome="Acme")
    capo = _utente("capo", "view_azienda", "change_azienda")
    lucia = _utente("lucia", "view_azienda")
    return acme, capo, lucia, TipoAttivita.objects.get(nome="Chiamata")


def test_tipi_iniziali(db):
    assert list(TipoAttivita.objects.values_list("nome", flat=True)) == ["Da fare", "Chiamata", "Email", "Riunione"]


def test_pianifica_con_scadenza_di_default(scena):
    acme, capo, lucia, chiamata = scena
    a = attivita.pianifica(acme, chiamata, lucia, riepilogo="Richiamare", creato_da=capo)
    assert a.scadenza == OGGI + datetime.timedelta(days=1) and attivita.stato(a) == "futura"


def test_segna_fatta_scrive_nel_chatter(scena):
    acme, capo, lucia, chiamata = scena
    a = attivita.pianifica(acme, chiamata, lucia, OGGI, "Richiamare")
    attivita.segna_fatta(a, lucia, "Risolto al telefono")
    assert not AttivitaPianificata.objects.exists()
    m = chatter.messaggi_di(acme).first()
    assert m.tipo == "sistema" and m.autore == lucia and m.corpo == "Chiamata fatta: Richiamare\nRisolto al telefono"
    assert mail.outbox == []


def test_pannello_e_pianifica_dalla_vista(client, scena):
    acme, capo, lucia, chiamata = scena
    client.force_login(capo)
    ct = ct_di(acme).pk
    r = client.post(f"/chatter/{ct}/{acme.pk}/pianifica/", {"tipo": chiamata.pk, "assegnatario": lucia.pk,
                                                            "scadenza": "2026-11-03", "riepilogo": "Offerta"},
                    HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and "Offerta" in r.content.decode()
    a = AttivitaPianificata.objects.get()
    assert (a.assegnatario, a.scadenza, a.creato_da) == (lucia, datetime.date(2026, 11, 3), capo)
    assert "Pianifica un'attività" in client.get(f"/core/aziende/{acme.pk}/").content.decode()


def test_pianificare_richiede_change(client, scena):
    acme, capo, lucia, chiamata = scena
    client.force_login(lucia)
    r = client.post(f"/chatter/{ct_di(acme).pk}/{acme.pk}/pianifica/", {"tipo": chiamata.pk})
    assert r.status_code == 403 and not AttivitaPianificata.objects.exists()


def test_fatta_e_annulla_permessi(client, scena):
    acme, capo, lucia, chiamata = scena
    estraneo = _utente("estraneo", "view_azienda")
    a = attivita.pianifica(acme, chiamata, lucia, OGGI, creato_da=capo)
    client.force_login(estraneo)
    assert client.post(f"/attivita/{a.pk}/fatta/").status_code == 403
    client.force_login(lucia)                                   # l'assegnataria può
    assert client.post(f"/attivita/{a.pk}/fatta/").status_code == 302
    b = attivita.pianifica(acme, chiamata, lucia, OGGI, creato_da=capo)
    client.force_login(capo)
    client.post(f"/attivita/{b.pk}/annulla/")
    assert not AttivitaPianificata.objects.exists()


def test_le_mie_attivita_e_contatore(client, scena):
    acme, capo, lucia, chiamata = scena
    attivita.pianifica(acme, chiamata, lucia, OGGI - datetime.timedelta(days=2), "Scaduta")
    attivita.pianifica(acme, chiamata, lucia, OGGI, "Di oggi")
    attivita.pianifica(acme, chiamata, lucia, OGGI + datetime.timedelta(days=5), "Futura")
    client.force_login(lucia)
    r = client.get("/attivita/")
    html = r.content.decode()
    assert html.index("Scaduta") < html.index("Di oggi") < html.index("Futura")
    assert f'href="/core/aziende/{acme.pk}/"' in html
    assert {"label": "Attività · 2", "url_name": "core:attivita"} in r.context["theme"]["nav"]
    assert "Le mie attività" in client.get("/app/").content.decode()
    client.force_login(capo)
    assert not any(v["url_name"] == "core:attivita" for v in client.get("/app/").context["theme"]["nav"])


def test_promemoria(scena):
    acme, capo, lucia, chiamata = scena
    attivita.pianifica(acme, chiamata, lucia, OGGI, "Richiamare Rossi")
    attivita.pianifica(acme, chiamata, capo, OGGI + datetime.timedelta(days=3), "Non ancora")
    assert attivita.promemoria() == 1
    (email,) = mail.outbox
    assert email.to == ["lucia@example.com"] and "Richiamare Rossi" in email.body and "/attivita/" in email.body
