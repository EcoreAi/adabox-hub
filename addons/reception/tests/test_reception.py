"""Le garanzie di base del modulo: restano valide anche quando aggiungi la tua logica."""
import pytest
from django.contrib.auth.models import Permission, User

from core.models import Azienda
from reception.models import Visita

pytestmark = pytest.mark.django_db
URL = "/reception/visite/"


def _utente(azienda, *permessi):
    u = User.objects.create_user("prova", "prova@example.com", "x")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="reception", codename__in=permessi))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def aziende():
    return Azienda.objects.first(), Azienda.objects.create(nome="Altra azienda")


def test_si_crea_e_si_apre(client, aziende):
    client.force_login(_utente(aziende[0], "view_visita", "add_visita"))
    assert client.post(URL + "nuovo/", {"nome": "Primo"}).status_code == 302
    voce = Visita.objects.get()
    assert voce.azienda == aziende[0]
    assert client.get(f"{URL}{voce.pk}/").status_code == 200


def test_un_altra_azienda_non_vede_i_dati(client, aziende):
    mia, altra = aziende
    Visita.objects.create(azienda=mia, nome="MIO")
    estraneo = Visita.objects.create(azienda=altra, nome="ESTRANEO")
    client.force_login(_utente(mia, "view_visita"))
    pagina = client.get(URL).content.decode()
    assert "MIO" in pagina and "ESTRANEO" not in pagina
    assert client.get(f"{URL}{estraneo.pk}/").status_code == 404


def test_senza_permesso_non_si_entra(client, aziende):
    client.force_login(_utente(aziende[0]))
    assert client.get(URL).status_code == 403


def _collega(azienda, nome):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.profilo.aziende.set([azienda])
    return u


def test_chiosco_entrata_avviso_e_uscita(client, aziende):
    from django.core import mail

    from core import chatter
    az = aziende[0]
    tablet = _utente(az, "add_visita", "view_visita")
    laura = _collega(az, "laura")
    client.force_login(tablet)
    pagina = client.get("/reception/chiosco/").content.decode()
    assert "Laura" in pagina and "informativa" in pagina.lower()
    assert client.post("/reception/chiosco/", {"nome": "Mario Rossi", "ospite": laura.pk}).status_code == 200   # senza privacy no
    assert not Visita.objects.exists()
    r = client.post("/reception/chiosco/", {"nome": "Mario  Rossi", "societa": "Acme", "ospite": laura.pk, "motivo": "Riunione", "privacy": "on"})
    assert r.status_code == 302
    v = Visita.objects.get()
    assert v.nome == "Mario Rossi" and v.stato == "presente" and v.privacy and chatter.segue(v, laura)
    assert any(e.to == ["laura@example.com"] and "arrivato in reception" in e.body for e in mail.outbox)
    pagina = client.get("/reception/chiosco/").content.decode()
    assert "Mario R." in pagina and "Acme" not in pagina                   # sul tablet niente dati degli altri
    client.post(f"/reception/chiosco/uscita/{v.pk}/")
    assert Visita.objects.get().stato == "uscito"


def test_visita_attesa_e_presenti(client, aziende):
    from django.utils import timezone

    from reception import servizi
    az = aziende[0]
    laura = _collega(az, "laura")
    attesa = Visita.objects.create(azienda=az, nome="Giulia Verdi", ospite=laura, prevista_il=timezone.now())
    client.force_login(_utente(az, "view_visita", "add_visita"))
    assert "Giulia Verdi" in client.get("/reception/presenti/").content.decode()       # tra gli attesi
    client.post("/reception/chiosco/", {"nome": "giulia verdi", "privacy": "on"})
    assert Visita.objects.count() == 1 and Visita.objects.get(pk=attesa.pk).ospite == laura   # usa quella attesa
    html = client.get("/reception/presenti/").content.decode()
    assert "Giulia Verdi" in html and "Stampa per l&#x27;evacuazione" in html or "Stampa per l'evacuazione" in html
    altra = Visita.objects.create(azienda=aziende[1], nome="Di un'altra", entrata=timezone.now())
    assert list(servizi.presenti(az)) == [Visita.objects.get(pk=attesa.pk)] and altra not in servizi.presenti(az)


def test_conservazione(aziende):
    from datetime import timedelta

    from django.utils import timezone

    from reception import servizi
    vecchia = Visita.objects.create(azienda=aziende[0], nome="Vecchia", entrata=timezone.now(), uscita=timezone.now())
    Visita.objects.filter(pk=vecchia.pk).update(creato=timezone.now() - timedelta(days=400))
    presente = Visita.objects.create(azienda=aziende[0], nome="Ancora dentro", entrata=timezone.now())
    Visita.objects.filter(pk=presente.pk).update(creato=timezone.now() - timedelta(days=400))
    assert servizi.cancella_vecchie() == 1 and list(Visita.objects.all()) == [Visita.objects.get(pk=presente.pk)]
