"""Barra in alto: poche app visibili, le altre nel menu "Altre"; app fisse scelte dall'amministratore;
l'app corrente resta sempre visibile."""
from django.contrib.auth.models import Permission, User

from core import barra
from core.models import Parametro


def _voci(n):
    return [{"label": f"App{i}", "url_name": f"app{i}:home", "slug": f"app{i}"} for i in range(n)]


def _slug(voci):
    return [v["slug"] for v in voci]


def test_poche_app_nessun_menu():
    principali, altre = barra.dividi(_voci(5), quante=4)                 # una sola in più: resta nella barra
    assert len(principali) == 5 and altre == []


def test_divide_dopo_quante():
    principali, altre = barra.dividi(_voci(9), quante=4)
    assert _slug(principali) == ["app0", "app1", "app2", "app3"]
    assert _slug(altre) == ["app4", "app5", "app6", "app7", "app8"]


def test_app_corrente_sempre_visibile():
    principali, altre = barra.dividi(_voci(9), {"slug": "app7"}, quante=4)
    assert _slug(principali) == ["app0", "app1", "app2", "app7"]
    assert _slug(altre) == ["app3", "app4", "app5", "app6", "app8"]
    assert barra.dividi(_voci(9), {"slug": "app1"}, quante=4)[0] == _voci(9)[:4]


def test_app_fisse_nell_ordine_scelto():
    principali, altre = barra.dividi(_voci(9), fisse=["app5", "app1", "sconosciuta"])
    assert _slug(principali) == ["app5", "app1"]                          # le app non viste si saltano
    assert _slug(altre) == ["app0", "app2", "app3", "app4", "app6", "app7", "app8"]
    principali, altre = barra.dividi(_voci(9), {"slug": "app8"}, fisse=["app5", "app1"])
    assert _slug(principali) == ["app5", "app8"] and "app1" in _slug(altre)       # barra piena: cede l'ultima
    principali, _ = barra.dividi(_voci(9), {"slug": "app8"}, fisse=["app5", "app1", "nascosta"])
    assert _slug(principali) == ["app5", "app1", "app8"]       # una fissa che l'utente non vede: c'è posto


def test_leggi_default_e_valori_non_validi(db, settings):
    settings.NAV_APP_VISIBILI = 3
    assert barra.leggi() == {"fisse": [], "quante": 3}
    Parametro.objects.create(chiave=barra.CHIAVE, valore={"fisse": ["crm", 7], "quante": 99})
    assert barra.leggi() == {"fisse": ["crm"], "quante": 3}


def test_pagina_impostazioni(client, superuser):
    assert "Scegli le app della barra" in client.get("/impostazioni/").content.decode()
    html = client.get("/impostazioni/barra/").content.decode()
    assert 'name="fissa_todo"' in html and "scelta automatica" in html
    r = client.post("/impostazioni/barra/", {"fissa_todo": "1", "ordine_todo": "2", "fissa_crm": "1",
                                             "ordine_crm": "1", "fissa_ai": "", "quante": "3"})
    assert r.status_code == 302 and barra.leggi() == {"fisse": ["crm", "todo"], "quante": 3}
    tema = client.get("/dashboard/").context["theme"]
    assert [v["label"] for v in tema["nav_principale"][1:3]] == ["CRM", "To-Do"]
    assert all(v["slug"] not in ("crm", "todo") for v in tema["nav_altre"])
    client.post("/impostazioni/barra/", {"ripristina": "1"})
    assert not Parametro.objects.filter(chiave=barra.CHIAVE).exists()


def test_pagina_solo_con_permesso(client, db):
    u = User.objects.create_user("x", password="x")
    client.force_login(u)
    assert client.get("/impostazioni/barra/").status_code == 403
    u.user_permissions.add(Permission.objects.get(codename="change_parametro"))
    client.force_login(User.objects.get(pk=u.pk))
    assert client.get("/impostazioni/barra/").status_code == 200


def test_header_con_menu_altre(client, superuser, settings):
    settings.NAV_APP_VISIBILI = 2
    r = client.get("/dashboard/")
    tema = r.context["theme"]
    assert len(tema["nav_principale"]) == 3 and tema["nav_altre"]
    assert 'aria-controls="nav-altre"' in r.content.decode()
