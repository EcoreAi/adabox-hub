"""Pagina «Strumenti»: elenco con lo stato di ogni strumento, spegnere per l'azienda o per tutta l'istanza, mai
riaccendere oltre la licenza."""
import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from ai.models import Licenza, StrumentoSpento
from ai.strumenti import registro
from ai.tests.test_licenza import _licenza, chiavi  # noqa: F401  (fixture)
from core.models import Azienda, RegistroModifica

URL = "/ai/strumenti/"


@pytest.fixture
def admin_cliente(db, client):
    """Amministratore dell'assistente di un cliente: permessi dell'AI, non superutente."""
    azienda = Azienda.objects.first()
    u = User.objects.create_user("admin_cliente", password="x")
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    client.force_login(u)
    return User.objects.get(pk=u.pk), azienda


def _nomi(utente, azienda):
    return {s.nome for s in registro.disponibili(utente, azienda=azienda)}


def test_l_amministratore_spegne_per_la_sua_azienda_e_ada_non_lo_ha_piu(admin_cliente, client):
    utente, azienda = admin_cliente
    assert reverse("ai:strumenti") == URL
    html = client.get(URL).content.decode()
    assert "elimina_record" in html and "disponibile" in html and "Per l'azienda" in html
    assert 'value="istanza"' not in html                    # «Per tutti» è riservato al Global Admin
    assert "elimina_record" in _nomi(utente, azienda)
    r = client.post(URL, {"nome": "elimina_record", "livello": "azienda", "azione": "spegni"})
    assert r.status_code == 302 and StrumentoSpento.objects.filter(nome="elimina_record", azienda=azienda).exists()
    assert "elimina_record" not in _nomi(utente, azienda)
    assert "elimina_record" in _nomi(utente, Azienda.objects.create(nome="Altra"))   # solo per la sua azienda
    assert "spento per questa azienda" in client.get(URL).content.decode()
    client.post(URL, {"nome": "elimina_record", "livello": "azienda", "azione": "accendi"})
    assert not StrumentoSpento.objects.exists() and "elimina_record" in _nomi(utente, azienda)
    # spento e riacceso: tutti e due nel registro delle modifiche, con chi l'ha fatto
    voci = RegistroModifica.objects.filter(oggetto__contains="elimina_record", utente=utente)
    assert set(voci.values_list("azione", flat=True)) >= {"creato", "eliminato"} or voci.count() == 2


def test_per_tutta_l_istanza_solo_il_global_admin(admin_cliente, client, superuser):
    utente, azienda = admin_cliente
    client.force_login(utente)
    assert client.post(URL, {"nome": "ricorda", "livello": "istanza", "azione": "spegni"}).status_code == 403
    client.force_login(superuser)
    assert 'value="istanza"' in client.get(URL).content.decode()
    client.post(URL, {"nome": "ricorda", "livello": "istanza", "azione": "spegni"})
    assert StrumentoSpento.objects.filter(nome="ricorda", azienda__isnull=True).exists()
    assert "ricorda" not in _nomi(utente, azienda) and "ricorda" not in _nomi(utente, None)


def test_richieste_non_valide_e_senza_permesso(admin_cliente, client, db):
    assert client.post(URL, {"nome": "non_esiste", "livello": "azienda", "azione": "spegni"}).status_code == 400
    assert client.post(URL, {"nome": "ricorda", "livello": "ovunque", "azione": "spegni"}).status_code == 400
    senza = User.objects.create_user("senza", password="x")
    client.force_login(senza)
    assert client.get(URL).status_code == 403


def test_fuori_licenza_si_vede_il_motivo_e_non_si_riaccende(admin_cliente, client, chiavi):  # noqa: F811
    utente, azienda = admin_cliente
    Licenza.objects.create(testo=_licenza(chiavi, funzioni=["memoria"]))
    html = client.get(URL).content.decode()
    assert "funzione non compresa nella licenza" in html
    client.post(URL, {"nome": "crea_record", "livello": "azienda", "azione": "spegni"})
    client.post(URL, {"nome": "crea_record", "livello": "azienda", "azione": "accendi"})
    assert "crea_record" not in _nomi(utente, azienda)     # riaccendere non scavalca la licenza
