import pytest

from core.models import Azienda, Lavoro
from core.tests.urls_righe import VISTA

pytestmark = [pytest.mark.urls("core.tests.urls_righe"), pytest.mark.django_db]


def _dati(nome, righe, totale=None, iniziali=0):
    dati = {"nome": nome, "righe0-TOTAL_FORMS": str(totale if totale is not None else len(righe)),
            "righe0-INITIAL_FORMS": str(iniziali), "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000"}
    for i, riga in enumerate(righe):
        dati.update({f"righe0-{i}-{k}": v for k, v in riga.items()})
    return dati


def test_form_con_righe(client, superuser):
    html = client.get("/prova/documenti/nuovo/").content.decode()
    assert 'name="righe0-TOTAL_FORMS"' in html and "data-aggiungi-riga" in html and "__prefix__" in html
    assert "core/righe.js" in html


def test_crea_documento_con_righe(client, superuser):
    VISTA.chiamate.clear()
    r = client.post("/prova/documenti/nuovo/", _dati("Doc", [{"funzione": "a.uno", "max_tentativi": "3"},
                                                            {"funzione": "a.due", "max_tentativi": "1"},
                                                            {"funzione": "", "max_tentativi": "3"}]))   # riga vuota
    doc = Azienda.objects.get(nome="Doc")
    assert r.status_code == 302 and sorted(doc.lavoro_set.values_list("funzione", flat=True)) == ["a.due", "a.uno"]
    assert VISTA.chiamate == [doc.pk]
    html = client.get(f"/prova/documenti/{doc.pk}/").content.decode()
    assert "a.uno" in html and "ui-totali-documento" in html and "<dt>Righe</dt><dd>2</dd>" in html


def test_modifica_ed_elimina_righe(client, superuser):
    doc = Azienda.objects.create(nome="Doc")
    a = Lavoro.objects.create(azienda=doc, funzione="a.uno")
    b = Lavoro.objects.create(azienda=doc, funzione="a.due")
    dati = _dati("Doc", [{"id": str(a.pk), "funzione": "a.uno.mod", "max_tentativi": "3"},
                         {"id": str(b.pk), "funzione": "a.due", "max_tentativi": "3", "DELETE": "on"}], iniziali=2)
    assert client.post(f"/prova/documenti/{doc.pk}/modifica/", dati).status_code == 302
    assert list(doc.lavoro_set.values_list("funzione", flat=True)) == ["a.uno.mod"]


def test_riga_non_valida_non_salva_niente(client, superuser):
    r = client.post("/prova/documenti/nuovo/", _dati("Doc", [{"funzione": "a.uno", "max_tentativi": "tanti"}]))
    assert r.status_code == 200 and "ui-field-error" in r.content.decode()
    assert not Azienda.objects.filter(nome="Doc").exists()
