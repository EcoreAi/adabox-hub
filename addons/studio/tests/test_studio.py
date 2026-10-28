import io
import json

import pytest
from django.contrib.contenttypes.models import ContentType

from core.models import Azienda, CampoPersonalizzato
from studio import campi, servizi
from studio.models import Personalizzazione

URL = "/studio/core/aziende/"


@pytest.fixture
def vista(db):
    return servizi.trova("core", "aziende")


def _salva(client, **dati):
    return client.post(URL, {"dati": json.dumps(dati)})


def test_indice_ed_editor(client, superuser, vista):
    html = client.get("/studio/").content.decode()
    assert URL in html
    html = client.get(URL).content.decode()
    assert 'id="studio-stato"' in html and "studio.js" in html


def test_permessi(client, utente, vista):
    client.force_login(utente)
    assert client.get("/studio/").status_code == 403 and client.get(URL).status_code == 403


def test_disponibili_e_obbligatori(vista):
    disp = campi.disponibili(vista)
    colonne = dict(disp["list_display"])
    assert colonne["nome"] == "Nome" and "citta" in colonne and "__str__" in colonne
    assert "attiva" in dict(disp["list_filter"]) and "nome" in dict(disp["search_fields"])
    assert "logo" in dict(disp["form"]) and campi.obbligatori(vista) == ["nome"]


def test_salva_applica_e_tiene_solo_le_differenze(client, superuser, vista):
    originali = campi.valori_originali(vista)
    r = _salva(client, **{**originali, "list_display": ["nome", "email"], "etichette": {"email": "Posta"},
                          "per_page": 20})
    assert r.status_code == 302
    p = Personalizzazione.objects.get()
    assert p.dati == {"list_display": ["nome", "email"], "etichette": {"email": "Posta"}, "per_page": 20}
    assert p.modificato_da.is_superuser
    lista = client.get("/core/aziende/").content.decode()
    assert "Posta" in lista and "Partita IVA" not in lista
    assert "personalizzata" in client.get("/studio/").content.decode()


def test_errori_non_salvano(client, superuser, vista):
    originali = campi.valori_originali(vista)
    r = _salva(client, list_display=[], form_layout=[["X", [["email"]]]], list_filter=["inesistente"])
    html = r.content.decode()
    assert r.status_code == 200 and not Personalizzazione.objects.exists()
    assert "almeno una colonna" in html and "obbligatori: nome" in html and "inesistente" in html
    r = client.post(URL, {"dati": "non json"})
    assert "non validi" in r.content.decode()
    assert originali == campi.valori_originali(vista)


def test_campi_spariti_scartati_a_runtime(vista):
    Personalizzazione.objects.create(modulo="core", vista="aziende",
                                     dati={"list_display": ["nome", "vecchio_campo"], "per_page": 3,
                                           "form_layout": [["A", [["nome", "sparito"]]]], "etichette": {"x": "y"}})
    applicati = servizi.per_vista(vista, None)
    assert applicati == {"list_display": ["nome"], "form_layout": [["A", [["nome"]]]], "etichette": {}}


def test_storico_e_ripristino(client, superuser, vista):
    originali = campi.valori_originali(vista)
    _salva(client, **{**originali, "list_display": ["nome"]})
    _salva(client, **{**originali, "list_display": ["nome", "citta"]})
    p = Personalizzazione.objects.get()
    assert p.dati["list_display"] == ["nome", "citta"] and p.storico[0]["dati"]["list_display"] == ["nome"]
    assert "Ripristina" in client.get(URL).content.decode()
    client.post(f"{URL}ripristina/", {"versione": "0"})
    p.refresh_from_db()
    assert p.dati["list_display"] == ["nome"] and len(p.storico) == 2
    client.post(f"{URL}ripristina/")
    p.refresh_from_db()
    assert p.dati == {} and servizi.per_vista(vista, None) == {}
    assert client.post(f"{URL}ripristina/", {"versione": "99"}).status_code == 404


def test_esporta_importa(client, superuser, vista):
    tipo = ContentType.objects.get_for_model(Azienda)
    CampoPersonalizzato.objects.create(modello=tipo, nome="settore", label="Settore")
    originali = campi.valori_originali(vista)
    _salva(client, **{**originali, "list_display": ["nome", "prop_settore"]})
    esportato = json.loads(client.get("/studio/esporta/").content)
    assert esportato["formato"] == "adabox-studio" and esportato["campi"][0]["nome"] == "settore"
    Personalizzazione.objects.all().delete()
    CampoPersonalizzato.objects.all().delete()
    esportato["personalizzazioni"].append({"modulo": "nessuno", "vista": "x", "dati": {}})
    file = io.BytesIO(json.dumps(esportato).encode())
    file.name = "studio.json"
    r = client.post("/studio/importa/", {"file": file}, follow=True)
    html = r.content.decode()
    assert "Importati: 2" in html and "vista nessuno:x" in html
    assert Personalizzazione.objects.get().dati == {"list_display": ["nome", "prop_settore"]}
    assert CampoPersonalizzato.objects.get().label == "Settore"
    brutto = io.BytesIO(b'{"formato": "altro"}')
    brutto.name = "x.json"
    assert "non riuscita" in client.post("/studio/importa/", {"file": brutto}, follow=True).content.decode()


def test_form_personalizzato_con_campo_singolo(client, superuser, vista):
    CampoPersonalizzato.objects.create(modello=ContentType.objects.get_for_model(Azienda), nome="settore",
                                       label="Settore")
    originali = campi.valori_originali(vista)
    r = _salva(client, **{**originali, "form_layout": [["Base", [["nome", "prop_settore"]]]]})
    assert r.status_code == 302
    form = client.get("/core/aziende/1/modifica/").content.decode()
    assert 'name="prop_settore"' in form and 'name="telefono"' not in form


def test_dashboard(rf, superuser, vista):
    from studio.dashboard import kpi
    richiesta = rf.get("/")
    richiesta.user = superuser
    assert kpi(richiesta)["kpi"][0]["valore"] == 0
