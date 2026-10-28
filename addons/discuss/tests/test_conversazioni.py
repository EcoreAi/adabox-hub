import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile

from discuss import hooks, servizi, testo
from discuss.models import Canale, Iscrizione, Messaggio


def _utente(nome):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="discuss",
                                                     codename__in=["view_canale", "add_canale", "add_messaggio"]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def persone(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    return _utente("anna"), _utente("bruno"), _utente("carla")


def test_testo_leggero():
    html = testo.rendi('Ciao @anna, guarda **qui**: https://es.it/a?b=1&c=2 <script>x</script>\nfine')
    assert '<span class="ds-menzione">@anna</span>' in html and "<strong>qui</strong>" in html
    assert '<a href="https://es.it/a?b=1&amp;c=2" target="_blank"' in html
    assert "&lt;script&gt;" in html and "<br>fine" in html
    link = testo.rendi("https://es.it/@anna/profilo")
    assert "ds-menzione" not in link and link.count("<a ") == 1
    assert "mail@anna" in testo.rendi("scrivi a mail@anna")                    # non è una menzione


def test_menzionati(persone):
    anna, bruno, _ = persone
    assert [u.username for u in testo.menzionati("ciao @Anna e @bruno e @nessuno")] == ["anna", "bruno"]


def test_canale_pubblico_entra_scrivi_leggi(client, persone):
    anna, bruno, carla = persone
    canale = servizi.crea_canale("progetto", Canale.PUBBLICO, anna, [bruno])
    servizi.invia(canale, anna, "Primo messaggio")
    client.force_login(carla)
    html = client.get(f"/discuss/c/{canale.pk}/").content.decode()
    assert "Primo messaggio" in html and "Entra nel canale" in html
    assert client.post(f"/discuss/c/{canale.pk}/invia/", {"corpo": "x"}).status_code == 403
    client.post(f"/discuss/c/{canale.pk}/entra/")
    r = client.post(f"/discuss/c/{canale.pk}/invia/", {"corpo": "Ciao a tutti"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 204 and r["HX-Trigger"] == "ds-nuovi"
    assert canale.messaggi.last().autore == carla
    client.force_login(bruno)
    assert servizi.totale_non_letti(bruno) == 2
    html = client.get("/discuss/").content.decode()                      # porta all'ultima conversazione
    assert client.get("/discuss/").url == f"/discuss/c/{canale.pk}/"
    html = client.get(f"/discuss/c/{canale.pk}/").content.decode()
    assert "Nuovi messaggi" in html and "Ciao a tutti" in html
    assert servizi.totale_non_letti(bruno) == 0


def test_canale_privato(client, persone):
    anna, bruno, carla = persone
    canale = servizi.crea_canale("direzione", Canale.PRIVATO, anna, [bruno])
    client.force_login(carla)
    assert client.get(f"/discuss/c/{canale.pk}/").status_code == 404
    assert client.post(f"/discuss/c/{canale.pk}/entra/").status_code == 404
    client.force_login(bruno)
    client.post(f"/discuss/c/{canale.pk}/invita/", {"utenti": [carla.pk]})
    assert Iscrizione.objects.filter(canale=canale, utente=carla).exists()


def test_polling_e_precedenti(client, persone, monkeypatch):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna, [bruno])
    primo = servizi.invia(canale, anna, "uno")
    client.force_login(bruno)
    r = client.get(f"/discuss/c/{canale.pk}/nuovi/?dopo={primo.pk}").content.decode()
    assert "uno" not in r and f"dopo={primo.pk}" in r
    secondo = servizi.invia(canale, anna, "due")
    r = client.get(f"/discuss/c/{canale.pk}/nuovi/?dopo={primo.pk}").content.decode()
    assert "due" in r and f"dopo={secondo.pk}" in r and 'id="ds-poller"' in r
    assert Iscrizione.objects.get(canale=canale, utente=bruno).ultimo_letto == secondo.pk
    monkeypatch.setattr(servizi, "PAGINA", 1)
    html = client.get(f"/discuss/c/{canale.pk}/").content.decode()
    assert "Messaggi precedenti" in html
    r = client.get(f"/discuss/c/{canale.pk}/precedenti/?prima={secondo.pk}").content.decode()
    assert "uno" in r


def test_messaggi_diretti(client, persone):
    anna, bruno, carla = persone
    client.force_login(anna)
    r = client.post("/discuss/diretto/", {"utenti": [bruno.pk]})
    canale = Canale.objects.get(tipo="diretto")
    assert r.url == f"/discuss/c/{canale.pk}/"
    client.post("/discuss/diretto/", {"utenti": [bruno.pk]})
    assert Canale.objects.filter(tipo="diretto").count() == 1                    # stessa conversazione
    assert canale.titolo_per(anna) == "Bruno" and canale.titolo_per(bruno) == "Anna"
    client.post("/discuss/diretto/", {"utenti": [bruno.pk, carla.pk]})
    assert Canale.objects.filter(tipo="diretto").count() == 2
    client.force_login(carla)
    assert client.get(f"/discuss/c/{canale.pk}/").status_code == 404
    assert client.post(f"/discuss/c/{canale.pk}/esci/").status_code == 404


def test_modifica_elimina_allegati(client, persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna, [bruno])
    client.force_login(anna)
    client.post(f"/discuss/c/{canale.pk}/invia/", {"corpo": "con file", "file": SimpleUploadedFile("nota.txt", b"ciao")})
    m = Messaggio.objects.get()
    from core import allegati
    allegato = allegati.di(m).get()
    assert client.get(f"/discuss/allegato/{allegato.pk}/").status_code == 200
    r = client.post(f"/discuss/m/{m.pk}/modifica/", {"corpo": "corretto"})
    m.refresh_from_db()
    assert m.corpo == "corretto" and m.modificato_il and "(modificato)" in r.content.decode()
    client.force_login(bruno)
    assert client.post(f"/discuss/m/{m.pk}/elimina/").status_code == 403
    client.force_login(anna)
    client.post(f"/discuss/m/{m.pk}/elimina/")
    m.refresh_from_db()
    assert m.eliminato and m.corpo == "" and not allegati.di(m).exists()


def test_messaggio_vuoto(client, persone):
    anna, _, _ = persone
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna)
    client.force_login(anna)
    r = client.post(f"/discuss/c/{canale.pk}/invia/", {"corpo": "   "}, HTTP_HX_REQUEST="true")
    assert r.status_code == 422 and not Messaggio.objects.exists()


def test_preferenze_ed_esci(client, persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna, [bruno])
    client.force_login(bruno)
    client.post(f"/discuss/c/{canale.pk}/preferenze/", {"notifiche": "tutto"})
    assert Iscrizione.objects.get(canale=canale, utente=bruno).notifiche == "tutto"
    client.post(f"/discuss/c/{canale.pk}/esci/")
    assert not Iscrizione.objects.filter(canale=canale, utente=bruno).exists()


def test_nuovo_canale_dal_form(client, persone):
    anna, bruno, _ = persone
    client.force_login(anna)
    client.post("/discuss/canale/nuovo/", {"nome": "marketing", "tipo": "privato", "membri": [bruno.pk]})
    canale = Canale.objects.get(nome="marketing")
    assert canale.tipo == "privato" and set(canale.membri.all()) == {anna, bruno}


def test_install_e_demo(persone, superuser):
    from django.contrib.auth.models import Group
    Group.objects.create(name="Discuss / Utente")
    hooks.post_install(None)
    hooks.demo(None)
    hooks.demo(None)
    generale = Canale.objects.get(nome="generale")
    assert generale.membri.count() == 4 and generale.messaggi.count() == 2
    assert Canale.objects.filter(nome="commerciale").exists()


def test_dashboard(rf, persone):
    from discuss.dashboard import kpi
    anna, bruno, _ = persone
    canale = servizi.crea_canale("x", Canale.PUBBLICO, anna, [bruno])
    servizi.invia(canale, anna, "ciao")
    richiesta = rf.get("/")
    richiesta.user = bruno
    assert kpi(richiesta)["kpi"][0]["valore"] == 1
