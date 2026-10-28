"""Barra in alto: poche app visibili, le altre nel menu "Altre"; l'app corrente resta sempre visibile."""
from core.context_processors import dividi_nav


def _voci(n):
    return [{"label": f"App{i}", "url_name": f"app{i}:home", "slug": f"app{i}"} for i in range(n)]


def _slug(voci):
    return [v["slug"] for v in voci]


def test_poche_app_nessun_menu():
    principali, altre = dividi_nav(_voci(5), quante=4)              # una sola in più: resta nella barra
    assert len(principali) == 5 and altre == []


def test_divide_dopo_quante():
    principali, altre = dividi_nav(_voci(9), quante=4)
    assert _slug(principali) == ["app0", "app1", "app2", "app3"]
    assert _slug(altre) == ["app4", "app5", "app6", "app7", "app8"]


def test_app_corrente_sempre_visibile():
    principali, altre = dividi_nav(_voci(9), {"slug": "app7"}, quante=4)
    assert _slug(principali) == ["app0", "app1", "app2", "app7"]
    assert _slug(altre) == ["app3", "app4", "app5", "app6", "app8"]
    assert dividi_nav(_voci(9), {"slug": "app1"}, quante=4)[0] == _voci(9)[:4]


def test_header_con_menu_altre(client, superuser, settings):
    settings.NAV_APP_VISIBILI = 2
    r = client.get("/dashboard/")
    tema = r.context["theme"]
    html = r.content.decode()
    if len(tema["nav"]) - 1 > 3:                                       # dipende dalle app caricate nei test
        assert len(tema["nav_principale"]) == 3 and tema["nav_altre"]
        assert 'aria-controls="nav-altre"' in html and tema["nav_altre"][0]["label"] in html
