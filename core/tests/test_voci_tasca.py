"""Le voci che i moduli aggiungono alla pagina «In tasca» (hooks.voce_tasca): per chi ha il permesso, con l'app accesa
e attiva per l'azienda corrente; se lo chiedono, anche tra le scorciatoie dell'icona dell'app installata."""
import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core import azienda as az
from core.models import Azienda, Modulo, ProfiloUtente
from core.registry import hooks, modules

pytestmark = pytest.mark.django_db


@pytest.fixture
def scansiona(monkeypatch):
    """Una voce registrata da un modulo: qui la prima pagina del CRM fa da «Scansiona documento»."""
    monkeypatch.setattr(hooks, "_tasca", [])
    pagina = modules.manifests_attivi()["crm"].menu[0]
    hooks.voce_tasca("Scansiona documento", pagina["url_name"], icona="search", permission=pagina["permission"],
                     sotto="DDT e fatture", conta=lambda request: 3, scorciatoia=True)
    hooks.voce_tasca("Scansiona documento", pagina["url_name"])           # registrata due volte (ready() rieseguito): una sola
    return pagina


def _operatore(client, pagina=None):
    u = User.objects.create_user("olga", "olga@example.com", "x")
    if pagina is not None:
        app, codice = pagina["permission"].split(".")
        u.user_permissions.add(Permission.objects.get(codename=codice, content_type__app_label=app))
    client.force_login(User.objects.get(pk=u.pk))
    return User.objects.get(pk=u.pk)


def test_la_voce_di_un_modulo_compare_per_chi_ha_il_permesso(client, scansiona):
    _operatore(client, scansiona)
    pagina = client.get("/tasca/").content.decode()
    assert "Scansiona documento" in pagina and "DDT e fatture" in pagina and f'href="{reverse(scansiona["url_name"])}"' in pagina
    assert pagina.count("Scansiona documento") == 1 and '<span class="tc-conta">3</span>' in pagina
    assert pagina.index("Scansiona documento") < pagina.index("Le mie attività")            # per prima: a un tocco dall'avvio


def test_senza_permesso_o_con_l_app_spenta_non_compare(client, scansiona, monkeypatch):
    _operatore(client)
    assert "Scansiona documento" not in client.get("/tasca/").content.decode()
    client.logout()
    User.objects.filter(username="olga").delete()
    _operatore(client, scansiona)
    assert "Scansiona documento" in client.get("/tasca/").content.decode()
    monkeypatch.setattr(modules, "disattivati", lambda: frozenset({"crm"}))
    assert "Scansiona documento" not in client.get("/tasca/").content.decode()


def test_con_l_app_riservata_a_un_altra_azienda_non_compare(client, superuser, scansiona):
    modules.sincronizza()
    zen, iem = Azienda.objects.get(pk=1), Azienda.objects.create(nome="IEM Srl")
    profilo, _ = ProfiloUtente.objects.get_or_create(utente=superuser)
    profilo.aziende.add(zen, iem)
    Modulo.objects.get(slug="crm").aziende.set([zen])

    def con(azienda):
        sessione = client.session
        sessione[az.CHIAVE_SESSIONE] = azienda.pk
        sessione.save()
        return client.get("/tasca/").content.decode()
    assert "Scansiona documento" in con(zen) and "Scansiona documento" not in con(iem)


def test_la_scorciatoia_dell_icona_passa_dagli_stessi_controlli(client, scansiona):
    scorciatoie = client.get("/manifest.webmanifest").json()["shortcuts"]
    assert scorciatoie[0] == {"name": "Scansiona documento", "url": f"/tasca/?apri={scansiona['url_name']}"}
    assert {"name": "In tasca", "url": "/tasca/?apri=tasca"} in scorciatoie               # quelle del kernel restano
    _operatore(client, scansiona)
    r = client.get(f"/tasca/?apri={scansiona['url_name']}")
    assert r.status_code == 302 and r["Location"] == reverse(scansiona["url_name"])
    client.logout()
    User.objects.filter(username="olga").delete()
    _operatore(client)                                                                   # senza permesso: resta «In tasca»
    assert client.get(f"/tasca/?apri={scansiona['url_name']}").status_code == 200


def test_un_bollino_che_va_in_errore_non_fa_cadere_la_pagina(client, superuser, monkeypatch):
    monkeypatch.setattr(hooks, "_tasca", [])
    pagina = modules.manifests_attivi()["crm"].menu[0]

    def rotto(request):
        raise RuntimeError("servizio spento")
    hooks.voce_tasca("Scansiona documento", pagina["url_name"], conta=rotto)
    hooks.voce_tasca("Pagina sparita", "modulo:che_non_c_e")
    html = client.get("/tasca/").content.decode()
    assert "Scansiona documento" in html and "Pagina sparita" not in html and client.get("/manifest.webmanifest").json()["shortcuts"][0]["name"] == "Parla con Ada"
