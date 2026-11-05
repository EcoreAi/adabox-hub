"""Chi non ha un'azienda corrente non vede nulla: né i record, né i nomi nei filtri e nelle scelte dei form."""
import pytest
from django.contrib.auth.models import Permission, User
from django.forms import modelform_factory

from acquisti.models import OrdineAcquisto
from contatti.models import Contatto
from core.models import Azienda
from core.viste.base import form_per_azienda
from todo.models import Attivita

pytestmark = pytest.mark.django_db


@pytest.fixture
def scena(client):
    """Due aziende con dati propri; l'utente vede solo A, con i permessi per leggere e creare."""
    a, b = Azienda.objects.first(), Azienda.objects.create(nome="Azienda B")
    for azienda, sigla in ((a, "A"), (b, "B")):
        Attivita.objects.create(titolo=f"ATTIVITA-{sigla}", azienda=azienda)
        fornitore = Contatto.objects.create(azienda=azienda, nome=f"FORNITORE-{sigla}", fornitore=True)
        OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore, numero=f"ORDINE-{sigla}")
    u = User.objects.create_user("utente", "u@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(codename__in=["view_attivita", "add_attivita", "view_ordineacquisto"]))
    u.profilo.aziende.set([a])
    u.profilo.azienda_predefinita = a
    u.profilo.save()
    client.force_login(u)
    return u, a, b


def _togli_aziende(u):
    u.profilo.aziende.clear()
    u.profilo.azienda_predefinita = None
    u.profilo.save()


def test_con_un_azienda_vede_solo_la_sua(client, scena):
    pagina = client.get("/todo/attivita/").content.decode()
    assert "ATTIVITA-A" in pagina and "ATTIVITA-B" not in pagina


@pytest.mark.parametrize("come", ["senza aziende", "azienda disattivata"])
def test_senza_azienda_corrente_la_lista_e_vuota(client, scena, come):
    u, a, b = scena
    if come == "senza aziende":
        _togli_aziende(u)
    else:
        u.profilo.aziende.set([b])
        Azienda.objects.filter(pk=b.pk).update(attiva=False)
    pagina = client.get("/todo/attivita/").content.decode()
    assert "ATTIVITA-A" not in pagina and "ATTIVITA-B" not in pagina


def test_senza_azienda_il_dettaglio_e_404(client, scena):
    _togli_aziende(scena[0])
    assert client.get(f"/todo/attivita/{Attivita.objects.first().pk}/").status_code == 404


def test_senza_azienda_non_si_crea(client, scena):
    _togli_aziende(scena[0])
    assert client.get("/todo/attivita/nuovo/").status_code == 403


def test_senza_azienda_i_filtri_non_mostrano_i_nomi(client, scena):
    assert "FORNITORE-B" not in client.get("/acquisti/ordini/").content.decode()
    _togli_aziende(scena[0])
    pagina = client.get("/acquisti/ordini/").content.decode()
    assert "FORNITORE-A" not in pagina and "FORNITORE-B" not in pagina and "ORDINE-B" not in pagina


def test_senza_azienda_il_kanban_e_vuoto(client, scena):
    _togli_aziende(scena[0])
    risposta = client.get("/acquisti/ordini/kanban/")
    assert risposta.status_code == 200
    pagina = risposta.content.decode()
    assert "FORNITORE-A" not in pagina and "ORDINE-B" not in pagina


def test_senza_azienda_le_scelte_dei_form_sono_vuote(scena):
    form = form_per_azienda(modelform_factory(OrdineAcquisto, fields=["fornitore"]), None)()
    assert not form.fields["fornitore"].queryset.exists()


def test_superuser_senza_aziende_non_fa_eccezione(client, scena):
    root = User.objects.create_superuser("root", "r@example.com", "pass12345!")
    _togli_aziende(root)
    client.force_login(root)
    assert "ATTIVITA-A" not in client.get("/todo/attivita/").content.decode()


def test_api_senza_azienda_non_restituisce_nulla(client, scena):
    from core.models import TokenApi
    u = scena[0]
    _, chiaro = TokenApi.genera(u, "prova")
    con_azienda = client.get("/api/v1/acquisti/ordini/", HTTP_AUTHORIZATION=f"Bearer {chiaro}")
    assert con_azienda.status_code == 200 and b"ORDINE-A" in con_azienda.content and b"ORDINE-B" not in con_azienda.content
    _togli_aziende(u)
    vuota = client.get("/api/v1/acquisti/ordini/", HTTP_AUTHORIZATION=f"Bearer {chiaro}")
    assert vuota.status_code == 200 and b"ORDINE-A" not in vuota.content and b"ORDINE-B" not in vuota.content
