"""Voci dei moduli nel menu del profilo (`menu_profilo` del manifest): validazione, permessi, posizione."""
import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core.models import Modulo
from core.registry import manifest, modules
from core.registry.manifest import Manifest, ManifestNonValido

VOCE = {"label": "Pannello", "url_name": "core:aziende_lista", "permission": "core.view_azienda", "icon": "users"}


def _errori(addons_tmp, slug="alfa", **extra):
    with pytest.raises(ManifestNonValido) as exc:
        manifest.leggi(addons_tmp.crea(slug, **extra))
    return str(exc.value)


def test_manifest_valido(addons_tmp):
    m = manifest.leggi(addons_tmp.crea("alfa", menu_profilo=[VOCE, {"label": "Senza", "url_name": "alfa:x"}]))
    assert m.menu_profilo[0] == VOCE and manifest.leggi(addons_tmp.crea("beta")).menu_profilo == []
    con_numero = {**VOCE, "conteggio": "alfa.decisioni.conteggio"}
    assert manifest.leggi(addons_tmp.crea("gamma", menu_profilo=[con_numero])).menu_profilo == [con_numero]


@pytest.mark.parametrize("voce,atteso", [
    ({"label": "A"}, "senza url_name"),
    ({"url_name": "alfa:x"}, "senza label"),
    ({"label": "A", "url_name": "senza_namespace"}, "atteso app:nome"),
    ({"label": "A", "url_name": "alfa:x", "permission": "alfa.*"}, "permission"),
    ({"label": "A", "url_name": "alfa:x", "icon": "<svg>"}, "icon"),
    ({"label": "A", "url_name": "alfa:x", "colore": "rosso"}, "chiavi sconosciute: colore"),
    ({"label": "A", "url_name": "alfa:x", "conteggio": "senza_punto"}, "conteggio"),
    ({"label": "A", "url_name": "alfa:x", "conteggio": 3}, "conteggio"),
    ("non un dizionario", "non è un dizionario"),
])
def test_manifest_non_valido(addons_tmp, voce, atteso):
    assert atteso in _errori(addons_tmp, menu_profilo=[voce])
    assert "attesa una lista" in _errori(addons_tmp, "beta", menu_profilo=VOCE)


def _m(slug, voci):
    return Manifest(slug=slug, percorso=None, name=slug.title(), version="1.0.0", min_core="1.0", menu_profilo=voci)


@pytest.fixture
def finti(monkeypatch):
    attivi = {"alfa": _m("alfa", [VOCE, {"label": "Rotta", "url_name": "alfa:inesistente"}]),
              "beta": _m("beta", [{"label": "Per tutti", "url_name": "core:stile", "icon": "shield"}])}
    monkeypatch.setattr(modules, "manifests_attivi", lambda: attivi)


@pytest.mark.django_db
def test_solo_con_il_permesso_e_tra_password_e_amministrazione(client, finti):
    u = User.objects.create_user("p", "p@example.com", "pass12345!", is_staff=True)
    client.force_login(u)
    pagina = client.get(reverse("core:dashboard")).content.decode()
    assert "Pannello" not in pagina and '<svg><use href="#icon-shield"/></svg> Per tutti' in pagina
    assert "Rotta" not in pagina                                                     # url non risolvibile: salta
    u.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_azienda"))
    client.force_login(User.objects.get(pk=u.pk))
    r = client.get(reverse("core:dashboard"))
    pagina = r.content.decode()
    assert [v["label"] for v in r.context["voci_profilo"]] == ["Pannello", "Per tutti"]
    assert f'<a href="{reverse("core:aziende_lista")}"><svg><use href="#icon-users"/></svg> Pannello</a>' in pagina
    assert pagina.index("Cambia password") < pagina.index("Pannello") < pagina.index("Amministrazione")
    assert "Pannello" not in [v["label"] for v in r.context["theme"]["nav"]]          # mai nella testata


@pytest.mark.django_db
def test_modulo_spento_nessuna_voce(client, finti, superuser):
    Modulo.objects.update_or_create(slug="beta", defaults={"nome": "Beta", "disattivato": True})
    assert [v["label"] for v in client.get(reverse("core:dashboard")).context["voci_profilo"]] == ["Pannello"]


def test_anonimo_nessuna_voce():
    from django.contrib.auth.models import AnonymousUser
    assert modules.voci_profilo(AnonymousUser()) == []


def tre(user):
    return 3


def zero(user):
    return 0


def rotto(user):
    raise RuntimeError("giù")


@pytest.mark.django_db
def test_conteggio_accanto_all_etichetta(client, superuser, monkeypatch):
    voci = [{"label": "Da approvare", "url_name": "core:stile", "conteggio": "core.tests.test_menu_profilo.tre"},
            {"label": "Niente", "url_name": "core:stile", "conteggio": "core.tests.test_menu_profilo.zero"},
            {"label": "Rotto", "url_name": "core:stile", "conteggio": "core.tests.test_menu_profilo.rotto"}]
    monkeypatch.setattr(modules, "manifests_attivi", lambda: {"alfa": _m("alfa", voci)})
    r = client.get(reverse("core:dashboard"))
    assert [(v["label"], v["conteggio"]) for v in r.context["voci_profilo"]] == [
        ("Da approvare (3)", 3), ("Niente", 0), ("Rotto", 0)]
    assert "Da approvare (3)</a>" in r.content.decode()
