"""Dipartimenti: le app di chi ne fa parte, con dipendenze, comuni ed eccezioni; gruppi, menu, middleware e pagine."""
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

import crm
import fatturazione
import fiscale
import vendite
from core import dipartimenti, ruoli
from core.models import Dipartimento, Modulo, Ruolo
from core.registry import manifest, modules
from core.registry.groups import crea_gruppi


@pytest.fixture
def gruppi(db):
    for app in (vendite, fatturazione, fiscale, crm):
        m = manifest.leggi(Path(app.__file__).parent)
        crea_gruppi(m)
        ruoli.gruppi_del_kernel(m)
    Modulo.objects.update_or_create(slug="todo", defaults={"nome": "To-do", "comune": True})
    return {r.nome: r for r in Ruolo.objects.all()}


def _utente(nome, ruolo=None, dip=(), **eccezioni):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    p = u.profilo
    p.ruolo, p.eccezioni = ruolo, eccezioni
    p.save()
    p.dipartimenti.set(dip)
    return User.objects.get(pk=u.pk)


def _nomi(u):
    return set(User.objects.get(pk=u.pk).groups.values_list("name", flat=True))


def _app(u):
    return {a["slug"] for a in modules.app_visibili(User.objects.get(pk=u.pk))}


def test_senza_dipartimenti_niente_cambia(gruppi):
    anna = _utente("anna", gruppi["Collaboratore"])
    assert "Vendite / Venditore" in _nomi(anna) and "crm" in _app(anna) and "vendite" in _app(anna)
    assert dipartimenti.consentite(anna) is dipartimenti.NESSUN_LIMITE


def test_il_dipartimento_restringe_gruppi_e_menu(gruppi):
    marketing = Dipartimento.objects.create(nome="Marketing", app=["crm"])
    mara = _utente("mara", gruppi["Collaboratore"], [marketing])
    assert not any(n.startswith(("Vendite /", "Fatturazione /")) for n in _nomi(mara))
    assert any(n.startswith("CRM /") for n in _nomi(mara))
    visibili = _app(mara)
    assert "crm" in visibili and "contatti" in dipartimenti.consentite(User.objects.get(pk=mara.pk))     # dipendenza del CRM
    assert "vendite" not in visibili and "fatturazione" not in visibili
    assert "todo" in dipartimenti.consentite(User.objects.get(pk=mara.pk))                              # comune


def test_dipendenze_piu_dipartimenti_e_tutte(gruppi):
    amm = Dipartimento.objects.create(nome="Amministrazione", app=["fatturazione"])
    marketing = Dipartimento.objects.create(nome="Marketing", app=["crm"])
    teo = _utente("teo", gruppi["Collaboratore"], [amm])
    consentite = dipartimenti.consentite(teo)
    assert {"fatturazione", "vendite", "prodotti", "contatti", "fiscale"} <= consentite and "crm" not in consentite
    teo.profilo.dipartimenti.add(marketing)                                    # in due dipartimenti: l'unione
    assert {"crm", "vendite"} <= _app(teo)
    direzione = Dipartimento.objects.create(nome="Direzione", tutte=True)
    dario = _utente("dario", gruppi["Collaboratore"], [marketing, direzione])
    assert dipartimenti.consentite(dario) is dipartimenti.NESSUN_LIMITE and "Vendite / Venditore" in _nomi(dario)


def test_eccezione_apre_fuori_dai_dipartimenti(gruppi):
    marketing = Dipartimento.objects.create(nome="Marketing", app=["crm"])
    eva = _utente("eva", gruppi["Collaboratore"], [marketing], vendite="lettura")
    assert "Vendite / Lettura" in _nomi(eva) and "vendite" in _app(eva)
    p = User.objects.get(pk=eva.pk).profilo
    assert ruoli.livello_effettivo(p, "vendite", dipartimenti.del_profilo(p)) == ("lettura", False)
    assert ruoli.livello_effettivo(p, "fatturazione", dipartimenti.del_profilo(p)) == ("nessuno", True)


def test_i_segnali_riallineano(gruppi):
    vendite_d = Dipartimento.objects.create(nome="Vendite", app=["crm"])
    ugo = _utente("ugo", gruppi["Collaboratore"], [vendite_d])
    assert "Vendite / Venditore" not in _nomi(ugo)
    vendite_d.app = ["crm", "vendite"]
    vendite_d.save()                                                          # app aggiunte: subito
    assert "Vendite / Venditore" in _nomi(ugo)
    vendite_d.profili.remove(ugo.profilo)
    assert "Fatturazione / Utente" in _nomi(ugo)                              # senza dipartimenti torna il ruolo pieno
    vendite_d.profili.add(ugo.profilo)
    assert "Fatturazione / Utente" not in _nomi(ugo)
    vendite_d.delete()
    assert "Fatturazione / Utente" in _nomi(ugo)


def test_middleware_e_superutente(gruppi, client):
    marketing = Dipartimento.objects.create(nome="Marketing", app=["crm"])
    mara = _utente("mara", gruppi["Manager"], [marketing])
    client.force_login(mara)
    r = client.get(reverse("vendite:ordini_lista"))
    assert r.status_code == 403 and "Fuori dai tuoi dipartimenti" in r.content.decode()
    assert client.get(reverse("crm:" + manifest.leggi(Path(crm.__file__).parent).menu[0]["url_name"].split(":")[1])).status_code == 200
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.dipartimenti.add(marketing)
    client.force_login(root)
    assert client.get(reverse("vendite:ordini_lista")).status_code == 200


def test_app_comune_dalla_scheda(gruppi, client):
    capo = _utente("capo", gruppi["Admin"])
    client.force_login(capo)
    marketing = Dipartimento.objects.create(nome="Marketing", app=["crm"])
    mara = _utente("mara", gruppi["Collaboratore"], [marketing])
    Modulo.objects.update_or_create(slug="vendite", defaults={"nome": "Vendite"})
    assert "vendite" not in _app(mara)
    html = client.get("/applicazioni/vendite/").content.decode()
    assert "Comune a tutti i dipartimenti" in html and "Marketing" in html
    assert client.post("/applicazioni/vendite/dipartimenti/", {"comune": "1"}).status_code == 302
    assert Modulo.objects.get(slug="vendite").comune and "Vendite / Venditore" in _nomi(mara) and "vendite" in _app(mara)
    client.post("/applicazioni/vendite/dipartimenti/", {"comune": "0", "dipartimenti": [marketing.pk]})
    marketing.refresh_from_db()
    assert not Modulo.objects.get(slug="vendite").comune and "vendite" in marketing.app and "vendite" in _app(mara)
    client.post("/applicazioni/vendite/dipartimenti/", {"comune": "0"})
    assert "vendite" not in _app(mara) and "Vendite / Venditore" not in _nomi(mara)


def test_pagine_dei_dipartimenti(gruppi, client):
    capo = _utente("capo", gruppi["Admin"])
    client.force_login(capo)
    mara = _utente("mara", gruppi["Collaboratore"])
    assert "Nessun dipartimento" in client.get("/utenti/dipartimenti/").content.decode()
    assert "Marketing" not in client.get("/utenti/dipartimenti/nuovo/").content.decode()
    r = client.post("/utenti/dipartimenti/nuovo/", {"nome": "Marketing", "descrizione": "Campagne", "ordine": 10, "app": ["crm", "inesistente"], "membri": [mara.pk]})
    assert r.status_code == 302
    d = Dipartimento.objects.get(nome="Marketing")
    assert d.app == ["crm"] and list(d.profili.values_list("utente__username", flat=True)) == ["mara"]
    assert "Vendite / Venditore" not in _nomi(mara)
    html = client.get(f"/utenti/dipartimenti/{d.pk}/").content.decode()
    assert "Contatti" in html                                                 # porta con sé la dipendenza
    assert "Marketing" in client.get("/utenti/").content.decode()
    html = client.get(f"/utenti/{mara.pk}/").content.decode()
    assert "fuori dai dipartimenti" in html
    assert "is-fuori" in client.get("/utenti/matrice/").content.decode()
    r = client.post(f"/utenti/{mara.pk}/", {"first_name": "Mara", "email": "mara@example.com", "username": "mara", "is_active": "on",
                                            "ruolo": gruppi["Collaboratore"].pk, "dipartimenti": []})
    assert r.status_code == 302 and not mara.profilo.dipartimenti.exists() and "Vendite / Venditore" in _nomi(mara)
    client.post(f"/utenti/{mara.pk}/", {"first_name": "Mara", "email": "mara@example.com", "username": "mara", "is_active": "on",
                                        "ruolo": gruppi["Collaboratore"].pk, "dipartimenti": [d.pk]})
    assert list(User.objects.get(pk=mara.pk).profilo.dipartimenti.all()) == [d]
    assert client.post(f"/utenti/dipartimenti/{d.pk}/elimina/").status_code == 302
    assert not Dipartimento.objects.exists() and "Vendite / Venditore" in _nomi(mara)


def test_solo_chi_gestisce(gruppi, client):
    anna = _utente("anna", gruppi["Collaboratore"])
    client.force_login(anna)
    for url in ("/utenti/dipartimenti/", "/utenti/dipartimenti/nuovo/"):
        assert client.get(url).status_code == 403, url


def test_app_nuove_nascono_comuni(db, settings):
    settings.DIPARTIMENTI_APP_COMUNI = ["todo"]
    Modulo.objects.filter(slug__in=["todo", "crm"]).delete()
    modules.sincronizza()
    assert Modulo.objects.get(slug="todo").comune and not Modulo.objects.get(slug="crm").comune
