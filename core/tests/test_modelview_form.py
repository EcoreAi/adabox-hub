import pytest
from django.contrib.auth.models import Permission, User
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.urls import reverse

from core.models import Azienda
from core.registry import hooks
from core.viste import registry


def _utente(client, *codenames, nome="op"):
    u = User.objects.create_user(nome, f"{nome}@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    return u


@pytest.fixture(autouse=True)
def _pulisci_hooks():
    hooks.svuota()
    yield
    hooks.svuota()


@pytest.fixture
def acme(db):
    return Azienda.objects.create(nome="Acme Spa", citta="Cagliari", telefono="070 123")


def _messaggi(r):
    return [str(m) for m in get_messages(r.wsgi_request)]


# --- form ---

@pytest.mark.django_db
def test_nuovo_senza_add_403(client):
    _utente(client, "view_azienda")
    assert client.get(reverse("core:aziende_nuovo")).status_code == 403


@pytest.mark.django_db
def test_nuovo_form_a_sezioni(client, monkeypatch):
    monkeypatch.setattr(registry.per_modello(Azienda), "readonly_fields", ["telefono"])
    _utente(client, "add_azienda", "view_azienda")
    r = client.get(reverse("core:aziende_nuovo"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "Anagrafica" in html and "Contatti" in html
    righe = html.split('class="ui-form-row"')
    assert any('name="partita_iva"' in r_ and 'name="codice_fiscale"' in r_ for r_ in righe)
    assert 'name="telefono"' not in html and 'name="email"' in html


@pytest.mark.django_db
def test_readonly_nel_dettaglio(client, acme, monkeypatch):
    monkeypatch.setattr(registry.per_modello(Azienda), "readonly_fields", ["telefono"])
    _utente(client, "view_azienda")
    assert "070 123" in client.get(reverse("core:aziende_dettaglio", kwargs={"pk": acme.pk})).content.decode()


@pytest.mark.django_db
def test_nuovo_post_valido(client):
    _utente(client, "add_azienda", "view_azienda")
    r = client.post(reverse("core:aziende_nuovo"), {"nome": "Nuova Srl", "attiva": "on"})
    nuova = Azienda.objects.get(nome="Nuova Srl")
    assert r.status_code == 302 and r["Location"] == reverse("core:aziende_dettaglio", kwargs={"pk": nuova.pk})
    assert any("«Nuova Srl»" in m for m in _messaggi(r))


@pytest.mark.django_db
def test_nuovo_post_non_valido(client):
    _utente(client, "add_azienda")
    r = client.post(reverse("core:aziende_nuovo"), {"nome": "", "email": "non-una-mail"})
    assert r.status_code == 200
    assert r.content.decode().count("ui-field-error") == 2


@pytest.mark.django_db
def test_modifica(client, acme):
    _utente(client, "change_azienda", "view_azienda")
    url = reverse("core:aziende_modifica", kwargs={"pk": acme.pk})
    assert 'value="Acme Spa"' in client.get(url).content.decode()
    r = client.post(url, {"nome": "Acme Group", "citta": "Cagliari", "attiva": "on"})
    assert r.status_code == 302
    acme.refresh_from_db()
    assert acme.nome == "Acme Group"


@pytest.mark.django_db
def test_modifica_senza_change_403(client, acme):
    _utente(client, "view_azienda")
    assert client.get(reverse("core:aziende_modifica", kwargs={"pk": acme.pk})).status_code == 403


# --- dettaglio ---

@pytest.mark.django_db
def test_dettaglio(client, acme):
    _utente(client, "view_azienda")
    html = client.get(reverse("core:aziende_dettaglio", kwargs={"pk": acme.pk})).content.decode()
    assert "Partita IVA" in html and "CAGLIARI" in html   # col_citta vale anche nel dettaglio
    assert reverse("core:aziende_modifica", kwargs={"pk": acme.pk}) not in html
    assert reverse("core:aziende_elimina", kwargs={"pk": acme.pk}) not in html
    assert reverse("core:aziende_bottone", kwargs={"pk": acme.pk, "nome": "attiva"}) not in html


@pytest.mark.django_db
def test_dettaglio_con_permessi(client, acme):
    _utente(client, "view_azienda", "change_azienda", "delete_azienda")
    html = client.get(reverse("core:aziende_dettaglio", kwargs={"pk": acme.pk})).content.decode()
    assert reverse("core:aziende_modifica", kwargs={"pk": acme.pk}) in html
    assert reverse("core:aziende_elimina", kwargs={"pk": acme.pk}) in html
    bottone = reverse("core:aziende_bottone", kwargs={"pk": acme.pk, "nome": "attiva"})
    assert f'<form method="post" action="{bottone}">' in html


@pytest.mark.django_db
def test_dettaglio_inesistente_404(client):
    _utente(client, "view_azienda")
    assert client.get(reverse("core:aziende_dettaglio", kwargs={"pk": 9999})).status_code == 404


# --- elimina ---

@pytest.mark.django_db
def test_elimina(client, acme):
    _utente(client, "view_azienda", "delete_azienda")
    url = reverse("core:aziende_elimina", kwargs={"pk": acme.pk})
    parziale = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "hx-post" in parziale and "<html" not in parziale
    assert "<html" in client.get(url).content.decode()
    r = client.post(url)
    assert r.status_code == 302 and r["Location"] == reverse("core:aziende_lista")
    assert not Azienda.objects.filter(pk=acme.pk).exists()
    assert any("Acme Spa" in m for m in _messaggi(r))


@pytest.mark.django_db
def test_elimina_htmx_redirect(client, acme):
    _utente(client, "view_azienda", "delete_azienda")
    r = client.post(reverse("core:aziende_elimina", kwargs={"pk": acme.pk}), HTTP_HX_REQUEST="true")
    assert r.status_code == 204 and r["HX-Redirect"] == reverse("core:aziende_lista")


@pytest.mark.django_db
def test_elimina_senza_permesso(client, acme):
    _utente(client, "view_azienda")
    assert client.post(reverse("core:aziende_elimina", kwargs={"pk": acme.pk})).status_code == 403


# --- azioni e bottoni ---

@pytest.mark.django_db
def test_azione_di_massa(client, acme):
    altra = Azienda.objects.create(nome="Beta")
    _utente(client, "view_azienda", "change_azienda")
    r = client.post(reverse("core:aziende_azione", kwargs={"nome": "disattiva"}), {"pk": [acme.pk, altra.pk]})
    assert r.status_code == 302 and r["Location"] == reverse("core:aziende_lista")
    assert not Azienda.objects.filter(pk__in=[acme.pk, altra.pk], attiva=True).exists()
    assert any("2" in m for m in _messaggi(r))


@pytest.mark.django_db
def test_azione_sconosciuta_404(client):
    _utente(client, "view_azienda", "change_azienda")
    assert client.post(reverse("core:aziende_azione", kwargs={"nome": "esplodi"}), {"pk": [1]}).status_code == 404


@pytest.mark.django_db
def test_lista_mostra_azioni_solo_se_dichiarate(client, acme, monkeypatch):
    _utente(client, "view_azienda", "change_azienda")
    html = client.get(reverse("core:aziende_lista")).content.decode()
    assert 'id="form-azioni"' in html and 'name="pk"' in html
    monkeypatch.setattr(registry.per_modello(Azienda), "actions", [])
    monkeypatch.setattr(registry.per_modello(Azienda), "reports", [])        # anche le stampe usano la selezione
    html = client.get(reverse("core:aziende_lista")).content.decode()
    assert 'id="form-azioni"' not in html and 'name="pk"' not in html


@pytest.mark.django_db
def test_bottone_messaggio(client, acme):
    acme.attiva = False
    acme.save()
    _utente(client, "view_azienda", "change_azienda")
    r = client.post(reverse("core:aziende_bottone", kwargs={"pk": acme.pk, "nome": "attiva"}))
    assert r.status_code == 302 and r["Location"] == reverse("core:aziende_dettaglio", kwargs={"pk": acme.pk})
    acme.refresh_from_db()
    assert acme.attiva


@pytest.mark.django_db
def test_bottone_risposta_diretta(client, acme, monkeypatch):
    vista = registry.per_modello(Azienda)
    monkeypatch.setattr(vista, "attiva", lambda request, obj: HttpResponse("diretta"))
    _utente(client, "view_azienda", "change_azienda")
    r = client.post(reverse("core:aziende_bottone", kwargs={"pk": acme.pk, "nome": "attiva"}))
    assert r.content == b"diretta"


# --- sezioni di dettaglio ---

@pytest.fixture
def templates_prova(settings, tmp_path):
    (tmp_path / "prova").mkdir()
    (tmp_path / "prova" / "_uno.html").write_text("<p>SEZIONE-UNO {{ obj.nome }}</p>")
    (tmp_path / "prova" / "_due.html").write_text("<p>SEZIONE-DUE</p>")
    settings.TEMPLATES = [{**settings.TEMPLATES[0], "DIRS": [tmp_path]}]


@pytest.mark.django_db
def test_sezioni_di_dettaglio(client, acme, templates_prova):
    hooks.sezione_dettaglio("core.Azienda", "prova/_due.html", order=20)
    hooks.sezione_dettaglio("core.Azienda", "prova/_uno.html", order=10)
    hooks.sezione_dettaglio(Azienda, "prova/_due.html", order=30, permission="core.delete_azienda")
    _utente(client, "view_azienda")
    html = client.get(reverse("core:aziende_dettaglio", kwargs={"pk": acme.pk})).content.decode()
    assert "SEZIONE-UNO Acme Spa" in html
    assert html.index("SEZIONE-UNO") < html.index("SEZIONE-DUE")
    assert html.count("SEZIONE-DUE") == 1
