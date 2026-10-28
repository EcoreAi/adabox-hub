import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from core import dashboard
from core.registry import modules
from core.registry.manifest import Manifest


@pytest.mark.django_db
def test_home_va_alla_chat_se_il_modulo_ai_e_installato(client, superuser):
    r = client.get("/")
    assert r.status_code == 302 and r["Location"] == "/ai/chat/"


@pytest.mark.django_db
def test_home_va_alla_dashboard_senza_modulo_con_home(client, superuser, monkeypatch):
    attivi = {k: v for k, v in modules.manifests_attivi().items() if not v.home}
    monkeypatch.setattr(modules, "manifests_attivi", lambda: attivi)
    r = client.get("/")
    assert r.status_code == 302 and r["Location"] == reverse("core:dashboard")


@pytest.mark.django_db
def test_dashboard_card_e_grafici(client, superuser):
    from todo.models import Attivita
    from core.models import Azienda
    Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="Da fare oggi")
    r = client.get(reverse("core:dashboard"))
    assert r.status_code == 200
    schede = {s["slug"]: s for s in r.context["schede"]}
    assert {"todo", "contatti", "calendario", "crm", "helpdesk", "progetti", "timesheet"} <= set(schede)
    assert schede["todo"]["kpi"][0] == {"valore": 1, "etichetta": "da fare"}
    html = r.content.decode()
    assert 'class="ui-dash-card" href="/todo/attivita/"' in html and "Attività per stato" in html and "<svg" in html


@pytest.mark.django_db
def test_kpi_rispettano_permessi_e_visibilita(client, db):
    u = User.objects.create_user("vuoto", "v@example.com", "x")
    client.force_login(u)
    assert client.get(reverse("core:dashboard")).context["schede"] == []        # nessuna app visibile
    from todo.models import Attivita
    assert dashboard.queryset(type("R", (), {"user": u, "azienda": None})(), Attivita).count() == 0


@pytest.mark.django_db
def test_app_con_errore_non_rompe_la_dashboard(client, superuser, monkeypatch):
    m = Manifest(slug="rotta", percorso=None, name="Rotta", version="1.0.0", min_core="1.0", application=True,
                 dashboard="modulo.che.non.esiste", menu=[{"label": "X", "url_name": "core:stile"}])
    monkeypatch.setattr(modules, "manifests_attivi", lambda: {"rotta": m})
    r = client.get(reverse("core:dashboard"))
    assert r.status_code == 200 and r.context["schede"] == []


@pytest.mark.django_db
def test_manifest_dashboard_e_home_validati(addons_tmp):
    from core.registry import manifest
    from core.registry.manifest import ManifestNonValido
    with pytest.raises(ManifestNonValido):
        manifest.leggi(addons_tmp.crea("alfa", dashboard="senza_punto"))
    with pytest.raises(ManifestNonValido):
        manifest.leggi(addons_tmp.crea("beta", home="senza_namespace"))
    assert manifest.leggi(addons_tmp.crea("gamma", dashboard="gamma.dashboard.kpi", home="gamma:pagina")).home == "gamma:pagina"
