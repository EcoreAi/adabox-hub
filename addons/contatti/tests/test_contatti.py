import json
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError

import contatti
from contatti import validatori
from contatti.models import Contatto
from core.models import Azienda
from core.registry import manifest
from core.registry.groups import crea_gruppi

CARTELLA = Path(contatti.__file__).parent


@pytest.fixture
def utente_contatti(db, client):
    crea_gruppi(manifest.leggi(CARTELLA))
    u = User.objects.create_user("carla", "carla@example.com", "x")
    u.groups.add(Group.objects.get(name="Contatti / Utente"))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    return u


@pytest.fixture
def prima(db):
    return Azienda.objects.get(pk=1)


def test_validatori():
    assert validatori.partita_iva_valida("06363391001") and not validatori.partita_iva_valida("06363391002")
    assert not validatori.partita_iva_valida("123")
    assert validatori.codice_fiscale_valido("RSSMRA85T10A562S") and not validatori.codice_fiscale_valido("RSSMRA85T10A562X")
    assert validatori.codice_fiscale_valido("06363391001")             # società: 11 cifre
    with pytest.raises(ValidationError):
        validatori.valida_sdi("ABC")
    validatori.valida_sdi("M5UXCR1")


def test_manifest_e_fixture():
    m = manifest.leggi(CARTELLA)
    assert m.application and m.sequences[0]["codice"] == "contatti.contatto"
    demo = json.loads((CARTELLA / "data" / "demo.json").read_text())
    for r in demo:
        if r["fields"]["partita_iva"]:
            assert validatori.partita_iva_valida(r["fields"]["partita_iva"]), r["fields"]["nome"]


def test_clean(prima):
    acme = Contatto.objects.create(azienda=prima, nome="Acme", partita_iva="06363391001")
    doppione = Contatto(azienda=prima, nome="Acme bis", partita_iva="06363391001")
    with pytest.raises(ValidationError) as e:
        doppione.full_clean()
    assert "partita_iva" in e.value.message_dict
    zeta = Azienda.objects.create(nome="Zeta")
    Contatto(azienda=zeta, nome="Acme in Zeta", partita_iva="06363391001").full_clean()     # altra azienda: ammesso
    errata = Contatto(azienda=prima, nome="Società", tipo="azienda", societa=acme, codice_fiscale="rssmra85t10a562s")
    with pytest.raises(ValidationError) as e:
        errata.full_clean()
    assert "societa" in e.value.message_dict and errata.codice_fiscale == "RSSMRA85T10A562S"


def test_crea_dalla_vista_con_codice_e_chatter(client, utente_contatti, prima):
    r = client.post("/contatti/contatti/nuovo/", {"tipo": "azienda", "nome": "Nuova Srl", "partita_iva": "01234567897",
                                                  "nazione": "IT", "attivo": "on"})
    c = Contatto.objects.get(nome="Nuova Srl")
    assert r.status_code == 302 and c.codice == "C00001" and c.azienda == prima
    from core import chatter
    assert chatter.messaggi_di(c).exists()
    r = client.post("/contatti/contatti/nuovo/", {"tipo": "azienda", "nome": "Sbagliata", "partita_iva": "01234567890",
                                                  "nazione": "IT"})
    assert r.status_code == 200 and "Partita IVA non valida" in r.content.decode()


def test_sezione_persone_e_scelte_per_azienda(client, utente_contatti, prima):
    acme = Contatto.objects.create(azienda=prima, nome="Acme Spa")
    Contatto.objects.create(azienda=prima, nome="Anna Neri", tipo="persona", societa=acme, ruolo="Acquisti")
    html = client.get(f"/contatti/contatti/{acme.pk}/").content.decode()
    assert "Persone (1)" in html and "Anna Neri" in html and "Acquisti" in html
    zeta = Azienda.objects.create(nome="Zeta")
    estranea = Contatto.objects.create(azienda=zeta, nome="Di un'altra azienda")
    form = client.get("/contatti/contatti/nuovo/?tipo=persona&societa=" + str(acme.pk)).context["form"]
    scelte = list(form.fields["societa"].queryset)
    assert acme in scelte and estranea not in scelte                   # filtro per azienda del kernel
    assert form.initial["societa"] == str(acme.pk)


def test_lista_e_kanban(client, utente_contatti, prima):
    Contatto.objects.create(azienda=prima, nome="Cliente Srl", cliente=True)
    Contatto.objects.create(azienda=prima, nome="Fornitore Srl", fornitore=True)
    nomi = [o.nome for o, _ in client.get("/contatti/contatti/", {"f_cliente": "1"}).context["righe"]]
    assert nomi == ["Cliente Srl"]
    assert client.get("/contatti/contatti/kanban/").status_code == 200


def test_report_html(client, utente_contatti, prima):
    c = Contatto.objects.create(azienda=prima, nome="Stampata Srl", partita_iva="12345678903")
    html = client.get(f"/contatti/contatti/{c.pk}/stampa/0/", {"html": 1}).content.decode()
    assert "Stampata Srl" in html and "12345678903" in html


def test_post_install_numera_i_demo(prima):
    from contatti import hooks
    crea_gruppi(manifest.leggi(CARTELLA))
    a = Contatto.objects.create(azienda=prima, nome="Senza codice")
    hooks.post_install(None)
    a.refresh_from_db()
    assert a.codice.startswith("C")
