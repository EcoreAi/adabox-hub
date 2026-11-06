import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from core.models import Azienda


@pytest.fixture
def crm(db):
    from crm.models import FaseCrm, Opportunita
    az = Azienda.objects.get(pk=1)
    nuova = FaseCrm.objects.create(nome="Nuova", ordine=10)
    qualificata = FaseCrm.objects.create(nome="Qualificata", ordine=20)
    vinta = FaseCrm.objects.create(nome="Vinta", ordine=30, vinta=True)
    a = Opportunita.objects.create(azienda=az, titolo="Alfa", fase=nuova, valore_atteso=100)
    b = Opportunita.objects.create(azienda=az, titolo="Beta", fase=nuova, valore_atteso=900, priorita=0)
    return a, b, nuova, qualificata, vinta


LISTA_CRM = "/crm/opportunita/kanban/"


@pytest.mark.django_db
def test_lo_spostamento_si_registra_con_chi_quando_e_la_nota(client, superuser, crm):
    from core.models import Messaggio, SpostamentoKanban
    a, _, nuova, qualificata, _ = crm
    url = reverse("crm:opportunita_sposta", args=[a.pk])
    r = client.post(url, {"valore": qualificata.pk}, HTTP_HX_REQUEST="true")
    s = SpostamentoKanban.objects.get()
    assert r.status_code == 204 and r["X-Nota"] == reverse("core:kanban_nota", args=[s.pk])
    assert (s.da, s.a, s.utente, s.object_id) == (nuova.nome, qualificata.nome, superuser, a.pk) and s.quando
    assert client.post(url, {"valore": qualificata.pk}, HTTP_HX_REQUEST="true").status_code == 204 and SpostamentoKanban.objects.count() == 1      # stessa colonna: niente
    html = client.get(LISTA_CRM).content.decode()
    assert "ui-kanban-spostata" in html and f"{nuova.nome} → {qualificata.nome}" in html
    # la nota: nello spostamento e nello storico del record, senza email ai follower
    assert client.post(reverse("core:kanban_nota", args=[s.pk]), {"nota": "  "}).status_code == 400
    assert client.post(reverse("core:kanban_nota", args=[s.pk]), {"nota": "Ha chiamato il cliente"}).status_code == 204
    s.refresh_from_db()
    assert s.nota == "Ha chiamato il cliente"
    m = Messaggio.objects.filter(object_id=a.pk, tipo=Messaggio.NOTA).get()
    assert "Ha chiamato il cliente" in m.corpo and qualificata.nome in m.corpo
    # la nota è di chi ha spostato
    client.force_login(User.objects.create_superuser("altro", "a@example.com", "x"))
    assert client.post(reverse("core:kanban_nota", args=[s.pk]), {"nota": "no"}).status_code == 404
    client.force_login(superuser)
    r = client.get(LISTA_CRM, {"card": a.pk})
    assert r.status_code == 200 and "Ha chiamato il cliente" in r.content.decode() and 'data-pk="%d"' % a.pk in r.content.decode()


@pytest.mark.django_db
def test_colonne_a_pezzi_ordinabili_e_le_chiuse_ripiegate(client, superuser, crm, monkeypatch):
    a, b, nuova, _, vinta = crm
    r = client.get(LISTA_CRM)
    html = r.content.decode()
    col = next(c for c in r.context["colonne"] if c["valore"] == str(vinta.pk))
    assert col["ripiegata"] and "is-ripiegata" in html and "Vista compatta" in html and 'id="kb-trova"' in html
    assert not next(c for c in r.context["colonne"] if c["valore"] == str(nuova.pk))["ripiegata"]
    assert ("-valore_atteso", "Valore") in r.context["ordini"] and "ui-kanban-maniglia" in html
    # un pezzo di colonna e l'ordinamento scelto
    r = client.get(LISTA_CRM, {"colonna": nuova.pk, "ordine": "-valore_atteso"})
    corpo = r.content.decode()
    assert r["X-Altri"] == "0" and corpo.index("Beta") < corpo.index("Alfa") and "<html" not in corpo
    r = client.get(LISTA_CRM, {"colonna": nuova.pk, "ordine": "valore_atteso", "da": "1"})
    assert "Beta" in r.content.decode() and "Alfa" not in r.content.decode()
    assert client.get(LISTA_CRM, {"colonna": "9999"}).status_code == 400
    assert client.get(LISTA_CRM, {"colonna": nuova.pk, "ordine": "password; drop"}).status_code == 200      # non ammesso: resta il predefinito
    # ultimo spostamento: prima chi è stato spostato
    client.post(reverse("crm:opportunita_sposta", args=[b.pk]), {"valore": vinta.pk}, HTTP_HX_REQUEST="true")
    client.post(reverse("crm:opportunita_sposta", args=[b.pk]), {"valore": nuova.pk}, HTTP_HX_REQUEST="true")
    corpo = client.get(LISTA_CRM, {"colonna": nuova.pk, "ordine": "spostata"}).content.decode()
    assert corpo.index("Beta") < corpo.index("Alfa")
