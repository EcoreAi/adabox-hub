"""Ruoli: dai livelli ai gruppi dei moduli; pagine di utenti e ruoli; inviti; protezioni."""
import re
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import Client
from django.utils import timezone

import fatturazione
import fiscale
import vendite
from core import ruoli
from core.models import Azienda, DueFattori, Ruolo
from core.registry import manifest
from core.registry.groups import crea_gruppi


@pytest.fixture
def gruppi(db):
    """I gruppi di Vendite, Fatturazione e Fiscale come dopo l'installazione; i quattro ruoli vengono dalla migrazione."""
    for app in (vendite, fatturazione, fiscale):
        m = manifest.leggi(Path(app.__file__).parent)
        crea_gruppi(m)
        ruoli.gruppi_del_kernel(m)
    return {r.nome: r for r in Ruolo.objects.all()}


def _utente(nome, ruolo=None, **eccezioni):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    p = u.profilo
    p.ruolo, p.eccezioni = ruolo, eccezioni
    p.save()
    return User.objects.get(pk=u.pk)


def _nomi(u):
    return set(User.objects.get(pk=u.pk).groups.values_list("name", flat=True))


def _vendite():
    return manifest.leggi(Path(vendite.__file__).parent)


def test_i_livelli_diventano_gruppi(gruppi):
    anna = _utente("anna", gruppi["Collaboratore"])
    assert "Vendite / Venditore" in _nomi(anna) and "Vendite / Responsabile" not in _nomi(anna) and "Fatturazione / Utente" in _nomi(anna)
    anna.profilo.ruolo = gruppi["Manager"]
    anna.profilo.save()
    assert {"Vendite / Venditore", "Vendite / Responsabile"} <= _nomi(anna)
    anna.profilo.ruolo = gruppi["Lettore"]
    anna.profilo.save()
    anna = User.objects.get(pk=anna.pk)
    assert "Vendite / Lettura" in _nomi(anna) and "Vendite / Venditore" not in _nomi(anna) and "Fiscale / Lettura" in _nomi(anna)
    assert anna.has_perm("vendite.view_ordinevendita") and not anna.has_perm("vendite.add_ordinevendita")


def test_eccezioni_e_gruppi_estranei(gruppi):
    Group.objects.create(name="Progetto segreto")
    anna = _utente("anna", gruppi["Collaboratore"], vendite="nessuno")
    anna.groups.add(Group.objects.get(name="Progetto segreto"))
    ruoli.applica(anna)
    nomi = _nomi(anna)
    assert "Progetto segreto" in nomi and not any(n.startswith("Vendite") for n in nomi) and "Fatturazione / Utente" in nomi
    anna.profilo.eccezioni = {"vendite": "responsabile"}
    anna.profilo.save()
    assert "Vendite / Responsabile" in _nomi(anna) and "Progetto segreto" in _nomi(anna)


def test_senza_ruolo_non_si_tocca_niente(gruppi):
    luca = _utente("luca")
    luca.groups.add(Group.objects.get(name="Vendite / Responsabile"), Group.objects.get(name="Fatturazione / Utente"))
    assert ruoli.applica(luca) is False and ruoli.applica_a_tutti() == 0
    assert "Vendite / Responsabile" in _nomi(luca)
    luca.profilo.eccezioni = {"vendite": "lettura"}
    luca.profilo.save()                                     # si allinea solo Vendite
    nomi = _nomi(luca)
    assert "Vendite / Lettura" in nomi and "Vendite / Responsabile" not in nomi and "Fatturazione / Utente" in nomi


def test_amministra_la_piattaforma(gruppi):
    capo = _utente("capo", gruppi["Admin"])
    assert capo.is_staff and ruoli.PIATTAFORMA in _nomi(capo)
    assert capo.has_perm("auth.change_user") and capo.has_perm("core.change_parametro") and capo.has_perm("core.change_ruolo")
    capo.profilo.ruolo = gruppi["Collaboratore"]
    capo.profilo.save()
    capo = User.objects.get(pk=capo.pk)
    assert not capo.is_staff and ruoli.PIATTAFORMA not in _nomi(capo) and not capo.has_perm("auth.change_user")


def test_cambiare_un_ruolo_vale_per_tutti(gruppi):
    a, b = _utente("a", gruppi["Collaboratore"]), _utente("b", gruppi["Collaboratore"])
    r = gruppi["Collaboratore"]
    r.livelli = {"vendite": "nessuno"}
    r.save()
    assert not any(n.startswith("Vendite") for n in _nomi(a) | _nomi(b)) and "Fatturazione / Utente" in _nomi(a)


def test_ruolo_predefinito_ai_nuovi_utenti(gruppi):
    assert not Ruolo.objects.filter(predefinito=True).exists()           # di partenza nessuno: come prima dei ruoli
    Ruolo.objects.filter(nome="Collaboratore").update(predefinito=True)
    nuovo = User.objects.create_user("nuovo", "n@example.com", "x")
    assert nuovo.profilo.ruolo.nome == "Collaboratore" and "Vendite / Venditore" in _nomi(nuovo)


def test_gruppo_lettura_del_kernel_e_dichiarato(gruppi):
    assert ruoli.nome_lettura(_vendite()) == "Vendite / Lettura"
    codici = set(Group.objects.get(name="Vendite / Lettura").permissions.values_list("codename", flat=True))
    assert codici and all(c.startswith("view_") for c in codici)
    m_fiscale = manifest.leggi(Path(fiscale.__file__).parent)
    assert ruoli.gruppi_del_kernel(m_fiscale) == [] and ruoli.nome_lettura(m_fiscale) == "Fiscale / Lettura"


def test_livello_dedotto_dai_gruppi(gruppi):
    m = _vendite()
    assert ruoli.livello_dai_gruppi({"Vendite / Responsabile"}, m) == "responsabile"
    assert ruoli.livello_dai_gruppi({"Vendite / Venditore"}, m) == "lavoro"
    assert ruoli.livello_dai_gruppi({"Vendite / Lettura"}, m) == "lettura" and ruoli.livello_dai_gruppi(set(), m) == "nessuno"


@pytest.fixture
def capo(gruppi, client):
    u = _utente("capo", gruppi["Admin"])
    client.force_login(User.objects.get(pk=u.pk))
    return u


def test_pagine_invito_matrice(gruppi, capo, client, settings):
    settings.SITO_URL = "http://prova.test"
    root = User.objects.create_superuser("root", "r@example.com", "x")
    html = client.get("/utenti/").content.decode()
    assert "Capo" in html and "root" not in html                       # i superutenti li vede solo un superutente
    assert client.get(f"/utenti/{root.pk}/").status_code == 404
    azienda = Azienda.objects.get(pk=1)
    r = client.post("/utenti/nuovo/", {"first_name": "Mario", "last_name": "Rossi", "email": "Mario@Example.com", "username": "", "is_active": "on",
                                       "ruolo": gruppi["Collaboratore"].pk, "aziende": [azienda.pk], "invito": "on", "livello_vendite": "responsabile"})
    assert r.status_code == 302
    mario = User.objects.get(email="mario@example.com")
    assert mario.username == "mario" and not mario.has_usable_password()
    assert mario.profilo.ruolo.nome == "Collaboratore" and mario.profilo.eccezioni == {"vendite": "responsabile"} and list(mario.profilo.aziende.all()) == [azienda]
    assert "Vendite / Responsabile" in _nomi(mario) and "Fatturazione / Utente" in _nomi(mario)
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["mario@example.com"]
    link = re.search(r"http://prova\.test(/accounts/reset/\S+)", mail.outbox[0].body)
    risposta = Client().get(link[1], follow=True)
    assert risposta.status_code == 200 and "password" in risposta.content.decode().lower()
    assert client.get(f"/utenti/{mario.pk}/").status_code == 200
    html = client.get("/utenti/matrice/").content.decode()
    assert "Mario Rossi" in html and "is-eccezione" in html
    r = client.post(f"/utenti/{mario.pk}/livello/", {"modulo": "vendite", "livello": "ruolo"})
    assert r.status_code == 200 and User.objects.get(pk=mario.pk).profilo.eccezioni == {} and "Vendite / Responsabile" not in _nomi(mario)
    assert client.post(f"/utenti/{mario.pk}/livello/", {"modulo": "vendite", "livello": "boh"}).status_code == 400
    assert client.post(f"/utenti/{mario.pk}/invito/").status_code == 302 and len(mail.outbox) == 2
    DueFattori.objects.create(utente=mario, segreto_cifrato="x", attiva_dal=timezone.now())
    assert "Azzera la verifica" in client.get(f"/utenti/{mario.pk}/").content.decode()
    client.post(f"/utenti/{mario.pk}/due-fattori/")
    assert not DueFattori.objects.filter(utente=mario).exists()
    client.post("/utenti/nuovo/", {"first_name": "Maria", "email": "mario2@example.com", "username": "mario", "is_active": "on", "ruolo": gruppi["Collaboratore"].pk})
    assert User.objects.get(email="mario2@example.com").username == "mario2"
    r = client.post("/utenti/nuovo/", {"first_name": "X", "email": "mario@example.com", "is_active": "on"})
    assert r.status_code == 200 and "già un utente" in r.content.decode()


def test_protezioni(gruppi, capo, client):
    client.post(f"/utenti/{capo.pk}/", {"first_name": "Capo", "email": "capo@example.com", "username": "capo", "ruolo": gruppi["Collaboratore"].pk})
    dopo = User.objects.get(pk=capo.pk)
    assert dopo.is_active and dopo.profilo.ruolo.nome == "Admin"          # non ci si chiude fuori da soli
    anna = _utente("anna", gruppi["Collaboratore"])
    client.force_login(User.objects.get(pk=anna.pk))
    for url in ("/utenti/", "/utenti/nuovo/", "/utenti/matrice/", "/utenti/ruoli/", f"/utenti/{capo.pk}/"):
        assert client.get(url).status_code == 403, url
    assert "Utenti e ruoli" not in client.get("/dashboard/").content.decode()
    client.force_login(User.objects.get(pk=capo.pk))
    assert "Utenti e ruoli" in client.get("/dashboard/").content.decode()


def test_pagine_dei_ruoli(gruppi, capo, client):
    assert "Collaboratore" in client.get("/utenti/ruoli/").content.decode()
    r = client.post("/utenti/ruoli/nuovo/", {"nome": "Contabile", "descrizione": "Solo i soldi", "livello_base": "nessuno", "ordine": 50, "predefinito": "on",
                                             "livello_fatturazione": "responsabile", "livello_vendite": "lettura"})
    assert r.status_code == 302
    contabile = Ruolo.objects.get(nome="Contabile")
    assert contabile.livelli == {"fatturazione": "responsabile", "vendite": "lettura"} and contabile.predefinito
    assert not Ruolo.objects.exclude(pk=contabile.pk).filter(predefinito=True).exists()
    gina = _utente("gina", contabile)
    assert {"Fatturazione / Responsabile", "Vendite / Lettura"} <= _nomi(gina) and "Vendite / Venditore" not in _nomi(gina)
    assert client.get(f"/utenti/ruoli/{contabile.pk}/").status_code == 200
    assert client.post(f"/utenti/ruoli/{contabile.pk}/elimina/").status_code == 302 and Ruolo.objects.filter(pk=contabile.pk).exists()
    gina.profilo.ruolo = None
    gina.profilo.save()
    client.post(f"/utenti/ruoli/{contabile.pk}/elimina/")
    assert not Ruolo.objects.filter(pk=contabile.pk).exists()


def test_global_admin_e_tecnico_e_la_scala(gruppi):
    assert [r.nome for r in Ruolo.objects.all()] == ["Global Admin", "Admin", "Manager", "Supervisore", "Collaboratore", "Lettore"]
    g = _utente("g", gruppi["Global Admin"])
    assert g.is_superuser and g.is_staff
    g.profilo.ruolo = gruppi["Admin"]
    g.profilo.save()
    g = User.objects.get(pk=g.pk)
    assert not g.is_superuser and g.is_staff and ruoli.PIATTAFORMA in _nomi(g)
    s = _utente("s", gruppi["Supervisore"])
    assert "Vendite / Venditore" in _nomi(s) and "Vendite / Responsabile" not in _nomi(s) and gruppi["Supervisore"].livelli["spese"] == "responsabile"


def test_global_admin_lo_assegna_solo_un_superutente(gruppi, capo, client):
    assert "Global Admin" not in client.get("/utenti/nuovo/").content.decode()
    r = client.post("/utenti/nuovo/", {"first_name": "X", "email": "x@example.com", "is_active": "on", "ruolo": gruppi["Global Admin"].pk})
    assert r.status_code == 200 and not User.objects.filter(email="x@example.com").exists()
    assert client.get(f"/utenti/ruoli/{gruppi['Global Admin'].pk}/").status_code == 403
    assert 'name="tecnico"' not in client.get("/utenti/ruoli/nuovo/").content.decode()
    client.force_login(User.objects.create_superuser("root", "r@example.com", "x"))
    assert "Global Admin" in client.get("/utenti/nuovo/").content.decode() and 'name="tecnico"' in client.get("/utenti/ruoli/nuovo/").content.decode()
