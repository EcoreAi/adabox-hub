import datetime
import io

import pytest
from django import forms
from django.contrib.auth.models import Group, Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from core import importa
from core.models import Azienda
from core.viste import registry

URL = "/core/aziende/importa/"


@pytest.fixture(autouse=True)
def privati(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path


@pytest.fixture
def vista(monkeypatch):
    v = registry.per_modello(Azienda)
    monkeypatch.setattr(v, "import_key", "partita_iva")
    return v


def _csv(testo, nome="aziende.csv"):
    return SimpleUploadedFile(nome, ("﻿" + testo).encode("utf-8"))


def _carica(client, file):
    return client.post(URL, {"fase": "carica", "file": file})


def _mappa(r):
    return {f"col_{i}": scelto for i, _, scelto in r.context["intestazioni"]}


def test_carica_e_proposta(client, superuser, vista):
    r = _carica(client, _csv("Nome;Partita IVA;Città;colonna strana\nAcme;111;Roma;x\n"))
    assert r.context["fase"] == "mappa" and r.context["totale"] == 1
    assert [s for _, _, s in r.context["intestazioni"]] == ["nome", "partita_iva", "citta", ""]


def test_prova_a_secco_con_errori(client, superuser, vista):
    r = _carica(client, _csv("nome;email;attiva\nBuona;b@example.com;sì\n;non-una-mail;no\n"))
    r = client.post(URL, {"fase": "prova", **_mappa(r)})
    assert r.context["n_errori"] == 2
    assert {(e["riga"], e["campo"]) for e in r.context["errori"]} == {(3, "Nome"), (3, "Email")}
    assert not Azienda.objects.filter(nome="Buona").exists()
    r = client.post(URL, {"fase": "importa", **_mappa(r)})            # tutto o niente
    assert not Azienda.objects.filter(nome="Buona").exists()


def test_import_riuscito_e_aggiornamento(client, superuser, vista):
    Azienda.objects.create(nome="Vecchia", partita_iva="222", citta="Napoli")
    r = _carica(client, _csv("Nome;Partita IVA;Attiva\nNuova Srl;111;sì\nRinominata;222;no\n"))
    mappa = _mappa(r)
    r = client.post(URL, {"fase": "prova", "aggiorna": "1", **mappa})
    assert (r.context["n_errori"], r.context["nuovi"], r.context["aggiornati"]) == (0, 1, 1)
    r = client.post(URL, {"fase": "importa", "aggiorna": "1", **mappa})
    assert r.status_code == 302
    aggiornata = Azienda.objects.get(partita_iva="222")
    assert (aggiornata.nome, aggiornata.citta, aggiornata.attiva) == ("Rinominata", "Napoli", False)
    assert Azienda.objects.get(partita_iva="111").attiva is True
    assert not list((importa.cartella()).iterdir())                     # file temporaneo cancellato


def test_senza_aggiorna_crea_doppioni(client, superuser, vista):
    Azienda.objects.create(nome="Vecchia", partita_iva="222")
    r = _carica(client, _csv("nome;partita_iva\nAltra;222\n"))
    client.post(URL, {"fase": "importa", **_mappa(r)})
    assert Azienda.objects.filter(partita_iva="222").count() == 2


def test_xlsx(client, superuser, vista):
    libro = Workbook()
    libro.active.append(["Nome", "Città"])
    libro.active.append(["Da Excel", "Torino"])
    dati = io.BytesIO()
    libro.save(dati)
    r = _carica(client, SimpleUploadedFile("a.xlsx", dati.getvalue()))
    client.post(URL, {"fase": "importa", **_mappa(r)})
    assert Azienda.objects.get(nome="Da Excel").citta == "Torino"


def test_formato_non_supportato_e_permessi(client, superuser, vista):
    r = _carica(client, SimpleUploadedFile("a.txt", b"x"))
    assert r.context["fase"] == "carica"
    u = User.objects.create_user("lettore", "l@example.com", "x")
    u.user_permissions.add(Permission.objects.get(codename="view_azienda"))
    client.force_login(u)
    assert client.get(URL).status_code == 403


def test_senza_file_in_sessione(client, superuser, vista):
    r = client.post(URL, {"fase": "prova", "col_0": "nome"})
    assert r.status_code == 302


def test_grande_nel_worker(client, superuser, vista, settings):
    settings.IMPORT_SINCRONO_MAX = 1
    r = _carica(client, _csv("nome\nUno\nDue\n"))
    r = client.post(URL, {"fase": "importa", **_mappa(r)})
    assert r.status_code == 302 and Azienda.objects.filter(nome__in=["Uno", "Due"]).count() == 2


class _Form(forms.Form):
    gruppo = forms.ModelChoiceField(queryset=Group.objects.all())
    gruppi = forms.ModelMultipleChoiceField(queryset=Group.objects.all())
    stato = forms.ChoiceField(choices=[("a", "Aperta"), ("f", "Fatta")])
    quando = forms.DateField()
    attivo = forms.BooleanField(required=False)
    importo = forms.DecimalField()


@pytest.mark.django_db
def test_convertitore():
    g1, g2 = Group.objects.create(name="Vendite"), Group.objects.create(name="Acquisti")
    c = importa.Convertitore(_Form)
    assert c("gruppo", "vendite") == str(g1.pk) and c("gruppo", str(g2.pk)) == str(g2.pk)
    assert c("gruppi", "Vendite, acquisti") == [str(g1.pk), str(g2.pk)]
    assert c("stato", "fatta") == "f" and c("stato", "a") == "a"
    assert c("quando", "03/11/2026") == "2026-11-03" and c("quando", datetime.datetime(2026, 1, 2, 9)) == "2026-01-02"
    assert c("attivo", "Sì") == "on" and c("attivo", "no") == ""
    assert c("importo", "1.234,50") == "1234.50"
