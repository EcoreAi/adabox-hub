"""Analisi è parte della Dashboard: le sue pagine sono schede, non ha una voce nella barra, e nelle sue pagine l'header
resta quello della Dashboard. La scheda «Statistiche» raccoglie i grafici delle app, la libreria e le pagine."""
import re

import pytest
from django.urls import reverse

from core import barra
from core.registry import hooks, modules
from grafici.models import Pagina


def _voce_attiva(html):
    """L'etichetta della voce evidenziata nella barra in alto."""
    nav = html.split('aria-label="Principale"', 1)[1].split("</nav>", 1)[0]
    return re.findall(r'class="is-active">([^<]+)</a>', nav)


def test_analisi_e_parte_della_dashboard():
    assert "grafici" in hooks.parti_dashboard()


@pytest.mark.django_db
def test_niente_voce_analisi_nella_barra(client, superuser):
    tema = client.get(reverse("core:dashboard")).context["theme"]
    slug = [v["slug"] for v in tema["nav_principale"] + tema["nav_altre"]]
    assert "grafici" not in slug and barra.DASHBOARD in slug
    voci_app, _ = barra.voci(modules.app_visibili(superuser))
    assert "grafici" not in [v["slug"] for v in voci_app]
    assert 'name="fissa_grafici"' not in client.get("/impostazioni/barra/").content.decode()   # né tra quelle da scegliere


@pytest.mark.django_db
def test_nelle_schede_resta_l_header_della_dashboard(client, superuser):
    p = Pagina.objects.create(utente=superuser, titolo="Direzione")
    for url in (reverse("core:dashboard"), reverse("grafici:pagine"), reverse("grafici:pagina", args=[p.pk]),
                reverse("grafici:pagina_app", args=["todo"])):
        r = client.get(url)
        assert r.status_code == 200, url
        assert _voce_attiva(r.content.decode()) == ["Dashboard"], url
        assert r.context["app_corrente"] is None and 'class="ui-appbar"' not in r.content.decode(), url
    r = client.get(reverse("todo:attivita_lista"))                         # in un'app vera: la sua voce e il suo menu
    assert r.context["app_corrente"]["slug"] == "todo" and "Dashboard" not in _voce_attiva(r.content.decode())


@pytest.mark.django_db
def test_scheda_statistiche(client, superuser):
    html = client.get(reverse("core:dashboard")).content.decode()
    assert f'href="{reverse("grafici:pagine")}"' in html and ">Statistiche<" in html
    r = client.get(reverse("grafici:pagine"))
    html = r.content.decode()
    assert "<h1>Statistiche</h1>" in html and 'an-scheda is-attiva" href="/grafici/"' in html
    voci = {(a["app"], v["url"]) for a in r.context["grafici_app"] for v in a["voci"]}
    assert ("CRM", reverse("crm:opportunita_grafico")) in voci and ("Vendite", reverse("vendite:ordini_grafico")) in voci


@pytest.mark.django_db
def test_la_vista_a_grafico_delle_app_si_chiama_grafico(client, superuser):
    crm = next(a for a in modules.app_visibili(superuser) if a["slug"] == "crm")
    assert {v["label"] for v in crm["menu"] if v["url_name"].endswith("_grafico")} == {"Grafico"}
