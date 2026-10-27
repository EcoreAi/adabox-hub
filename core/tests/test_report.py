import pytest
from django.contrib.auth.models import Permission, User

from core import report
from core.models import Allegato, Azienda
from core.viste import registry

PDF = pytest.mark.skipif(not report.disponibile(), reason="WeasyPrint senza Pango: deploy/test-pdf.sh")


@pytest.fixture(autouse=True)
def privati(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path


@pytest.fixture
def aziende(db):
    return [Azienda.objects.create(nome=n, partita_iva=p, citta="Cagliari") for n, p in [("Acme", "111"), ("Beta", "222")]]


def _lettore(client):
    u = User.objects.create_user("lettore", "l@example.com", "x")
    u.user_permissions.add(Permission.objects.get(codename="view_azienda"))
    client.force_login(User.objects.get(pk=u.pk))
    return u


def test_html_del_report(client, aziende):
    _lettore(client)
    html = client.get(f"/core/aziende/{aziende[0].pk}/stampa/0/", {"html": 1}).content.decode()
    assert "Acme" in html and "111" in html and "counter(pages)" in html
    assert html.count('class="record"') == 1


def test_bottone_nel_dettaglio_e_nella_lista(client, aziende):
    _lettore(client)
    assert f"/core/aziende/{aziende[0].pk}/stampa/0/" in client.get(f"/core/aziende/{aziende[0].pk}/").content.decode()
    html = client.get("/core/aziende/").content.decode()
    assert "/core/aziende/stampa/0/" in html and 'name="pk"' in html


def test_indice_e_permessi(client, aziende, monkeypatch):
    assert client.get(f"/core/aziende/{aziende[0].pk}/stampa/0/").status_code == 302      # anonimo
    _lettore(client)
    assert client.get(f"/core/aziende/{aziende[0].pk}/stampa/5/").status_code == 404
    vista = registry.per_modello(Azienda)
    monkeypatch.setattr(vista, "get_queryset", lambda request: Azienda.objects.exclude(pk=aziende[0].pk))
    assert client.get(f"/core/aziende/{aziende[0].pk}/stampa/0/").status_code == 404


def test_stampa_di_massa_html(client, aziende):
    _lettore(client)
    r = client.post("/core/aziende/stampa/0/?html=1", {"pk": [a.pk for a in aziende]})
    html = r.content.decode()
    assert html.count('class="record"') == 2 and "Acme" in html and "Beta" in html


def test_senza_pango_503(client, aziende, monkeypatch):
    def manca(*a, **k):
        raise report.ReportNonDisponibile("manca Pango")
    monkeypatch.setattr(report, "pdf", manca)
    _lettore(client)
    r = client.get(f"/core/aziende/{aziende[0].pk}/stampa/0/")
    assert r.status_code == 503 and "Pango" in r.content.decode()


def test_massa_grande_nel_worker(client, aziende, settings, monkeypatch):
    settings.REPORT_SINCRONO_MAX = 1
    monkeypatch.setattr(report, "pdf", lambda html: b"%PDF-finto")
    u = _lettore(client)
    r = client.post("/core/aziende/stampa/0/", {"pk": [a.pk for a in aziende]})
    assert r.status_code == 302
    allegato = Allegato.objects.get()
    assert allegato.record == u and allegato.nome.endswith(".pdf")


@pytest.mark.pdf
@PDF
def test_pdf_vero(client, aziende):
    _lettore(client)
    r = client.get(f"/core/aziende/{aziende[0].pk}/stampa/0/")
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf" and r.content.startswith(b"%PDF")
