import json
import re

import pytest
from django.contrib.auth.models import Permission, User
from django.template import engines
from django.test import RequestFactory
from django.urls import reverse

from core.models import Azienda
from core.registry import modules
from core.viste import interroga
from core.viste.interroga import ErroreInterrogazione
from grafici.models import Grafico, Pagina


@pytest.fixture
def attivita(db):
    from todo.models import Attivita
    az = Azienda.objects.get(pk=1)
    Attivita.objects.create(azienda=az, titolo="Alfa")
    Attivita.objects.create(azienda=az, titolo="Beta", stato=Attivita.FATTA)
    Attivita.objects.create(azienda=az, titolo="Gamma", stato=Attivita.FATTA)
    return az


def _serie(html, dom):
    m = re.search(rf'<script id="{dom}" type="application/json">(.*?)</script>', html)
    return json.loads(m.group(1)) if m else None


def _richiesta(utente, azienda):
    request = RequestFactory().get("/")
    request.user, request.azienda = utente, azienda
    return request


@pytest.mark.django_db
def test_il_motore_del_kernel_calcola_una_specifica_anche_con_i_filtri_della_lista(superuser, attivita):
    request = _richiesta(superuser, attivita)
    r = interroga.calcola({"vista": "todo.attivita", "per": "stato", "misura": "count"}, request)
    assert dict(r["serie"]) == {"Aperta": 1, "Fatta": 2} and r["totale"] == 3
    r = interroga.calcola({"vista": "todo.attivita", "per": "stato", "lista": {"f_stato": "fatta", "q": ""}}, request)
    assert dict(r["serie"]) == {"Fatta": 2} and r["totale"] == 2
    r = interroga.calcola({"vista": "todo.attivita", "per": "stato", "filtri": {"titolo__icontains": "alf"}}, request)
    assert dict(r["serie"]) == {"Aperta": 1}
    for spec in ({"vista": "todo.inesistente", "per": "stato"}, {"vista": "todo.attivita", "per": "descrizione"},
                 {"vista": "todo.attivita", "per": ""}, {"vista": "todo.attivita", "per": "stato", "misura": "sum:titolo"}):
        with pytest.raises(ErroreInterrogazione):
            interroga.calcola(spec, request)
    assert interroga.etichetta_misura(interroga.vista_per_nome("todo.attivita", request), "count") == "Numero"


@pytest.mark.django_db
def test_la_dashboard_mostra_le_schede_e_il_modulo_spento_le_toglie(client, superuser, attivita, monkeypatch):
    html = client.get(reverse("core:dashboard")).content.decode()
    assert 'class="an-schede"' in html and "Panoramica" in html and reverse("grafici:pagina_app", args=["todo"]) in html
    monkeypatch.setattr(modules, "disattivati", lambda: frozenset({"grafici"}))
    assert "an-schede" not in client.get(reverse("core:dashboard")).content.decode()


@pytest.mark.django_db
def test_pagina_nuova_grafico_dalla_vista_e_disposizione_dei_widget(client, superuser, attivita):
    r = client.post(reverse("grafici:nuova"), {"titolo": "Direzione", "icona": "target"})
    p = Pagina.objects.get(utente=superuser, titolo="Direzione")
    assert r.status_code == 302 and r.url == reverse("grafici:pagina", args=[p.pk]) and p.icona == "target"
    # la vista Grafico di Todo offre «Salva in Analisi» con i parametri del momento
    html = client.get(reverse("todo:attivita_grafico") + "?per=stato&f_stato=fatta").content.decode()
    assert "Salva in Analisi" in html and 'name="vista" value="todo.attivita"' in html and "f_stato=fatta" in html
    r = client.post(reverse("grafici:salva_da_vista"), {
        "vista": "todo.attivita", "per": "stato", "misura": "count", "tipo": "torta", "filtri": "per=stato&f_stato=fatta&q=",
        "destinazione": str(p.pk), "titolo": "Fatte per stato"})
    g = Grafico.objects.get(utente=superuser)
    assert r.status_code == 302 and g.pagina == p and g.tipo == "torta" and g.spec["lista"] == {"f_stato": "fatta"}
    assert dict(g.dati["serie"]) == {"Fatta": 2} and g.origine == "vista" and g.aggiornato is not None
    html = client.get(reverse("grafici:pagina", args=[p.pk])).content.decode()
    serie = _serie(html, f"wd-g-{g.pk}")
    assert serie["tipo"] == "torta" and serie["etichette"] == ["Fatta"] and serie["valori"] == [2.0]
    assert 'id="wd-griglia"' in html and "Fatte per stato" in html and "ada-contesto" in html and "1 filtro" in html
    # un grafico in libreria è nel cassetto e, se compare nel layout, entra nella pagina
    lib = Grafico.objects.create(utente=superuser, titolo="Libero", spec={"vista": "todo.attivita", "per": "stato"})
    assert f'data-aggiungi="g:{lib.pk}"' in client.get(reverse("grafici:pagina", args=[p.pk])).content.decode()
    nuovo = {"widget": [{"id": f"g:{lib.pk}", "w": 4}, {"id": f"g:{g.pk}", "w": 1}, {"id": "finto:kpi", "w": 2}], "nascosti": []}
    r = client.post(reverse("grafici:layout", args=[p.pk]), json.dumps(nuovo), content_type="application/json")
    assert r.status_code == 200 and r.json()["widget"] == [{"id": f"g:{lib.pk}", "w": 4}, {"id": f"g:{g.pk}", "w": 1}]
    lib.refresh_from_db()
    assert lib.pagina == p
    r = client.get(reverse("grafici:pagina", args=[p.pk]))
    assert [(w["id"], w["w"]) for w in r.context["widget"]] == [(f"g:{lib.pk}", 4), (f"g:{g.pk}", 1)]
    assert client.post(reverse("grafici:layout", args=[p.pk]), "[1]", content_type="application/json").status_code == 400
    assert client.post(reverse("grafici:ripristina", args=[p.pk])).status_code == 302 and Pagina.objects.get(pk=p.pk).layout == {}
    # rinomina, condividi, elimina (i grafici restano in libreria)
    client.post(reverse("grafici:modifica", args=[p.pk]), {"titolo": "Direzione 2026", "icona": "briefcase"})
    client.post(reverse("grafici:condividi", args=[p.pk]))
    p.refresh_from_db()
    assert (p.titolo, p.icona, p.condivisa) == ("Direzione 2026", "briefcase", True)
    assert client.post(reverse("grafici:elimina", args=[p.pk])).status_code == 302
    assert not Pagina.objects.filter(pk=p.pk).exists() and Grafico.objects.filter(pagina__isnull=True).count() == 2
    assert "Libero" in client.get(reverse("grafici:pagine")).content.decode()


@pytest.mark.django_db
def test_tipo_csv_aggiornamento_pagina_grande_ed_eliminazione(client, superuser, attivita):
    p = Pagina.objects.create(utente=superuser, titolo="P")
    g = Grafico.objects.create(utente=superuser, pagina=p, titolo="Per stato", spec={"vista": "todo.attivita", "per": "stato"})
    r = client.post(reverse("grafici:grafico_tipo", args=[g.pk]), {"tipo": "barre_orizzontali"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and Grafico.objects.get(pk=g.pk).tipo == "barre_orizzontali"
    assert client.post(reverse("grafici:grafico_tipo", args=[g.pk]), {"tipo": "kpi"}, HTTP_HX_REQUEST="true").status_code == 400
    r = client.post(reverse("grafici:grafico_aggiorna", args=[g.pk]), HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert r.status_code == 200 and f'id="an-widget-{g.pk}"' in html and _serie(html, f"wd-g-{g.pk}")["valori"] == [1.0, 2.0]
    g.refresh_from_db()
    assert g.aggiornato is not None and dict(g.dati["serie"]) == {"Aperta": 1, "Fatta": 2}
    r = client.get(reverse("grafici:grafico_csv", args=[g.pk]))
    testo = r.content.decode("utf-8-sig")
    assert r.status_code == 200 and testo.startswith("Categoria;Valore") and "Fatta;2" in testo
    html = client.get(reverse("grafici:grafico", args=[g.pk])).content.decode()
    assert "Per stato" in html and "Impostazioni" in html and _serie(html, f"wd-g-{g.pk}")["tipo"] == "barre_orizzontali"
    client.post(reverse("grafici:grafico_modifica", args=[g.pk]), {"titolo": "Stati delle attività", "destinazione": ""})
    g.refresh_from_db()
    assert g.titolo == "Stati delle attività" and g.pagina is None
    assert client.post(reverse("grafici:grafico_elimina", args=[g.pk])).status_code == 302 and not Grafico.objects.filter(pk=g.pk).exists()


@pytest.mark.django_db
def test_pagina_condivisa_in_sola_lettura_con_i_permessi_di_chi_guarda_e_privata_nascosta(client, superuser, attivita):
    privata = Pagina.objects.create(utente=superuser, titolo="Privata")
    condivisa = Pagina.objects.create(utente=superuser, titolo="Di tutti", condivisa=True)
    g = Grafico.objects.create(utente=superuser, pagina=condivisa, titolo="Stati", spec={"vista": "todo.attivita", "per": "stato"})
    altro = User.objects.create_user("altro", "a@example.com", "x")
    altro.user_permissions.set(Permission.objects.filter(content_type__app_label="grafici"))
    client.force_login(altro)
    assert client.get(reverse("grafici:pagina", args=[privata.pk])).status_code == 404
    r = client.get(reverse("grafici:pagina", args=[condivisa.pk]))
    html = r.content.decode()
    assert r.status_code == 200 and "Di tutti" in html and 'id="wd-modifica"' not in html and 'id="wd-griglia"' not in html
    assert "Stati" in html and "an-errore" in html                 # senza permesso su Todo il grafico non si calcola, la pagina regge
    assert Grafico.objects.get(pk=g.pk).aggiornato is None          # e la cache del proprietario non si tocca
    assert client.post(reverse("grafici:layout", args=[condivisa.pk]), "{}", content_type="application/json").status_code == 404
    html = client.get(reverse("core:dashboard")).content.decode()
    assert "Di tutti" in html and "Privata" not in html


@pytest.mark.django_db
def test_scheda_di_un_app_con_i_widget_del_manifest_si_nasconde_e_riappare(client, superuser, attivita):
    r = client.get(reverse("grafici:pagina_app", args=["todo"]))
    p = Pagina.objects.get(utente=superuser, app="todo")
    assert r.status_code == 200 and "todo:kpi" in [w["id"] for w in r.context["widget"]] and p.titolo
    assert client.get(reverse("grafici:pagina_app", args=["inesistente"])).status_code == 404
    assert client.post(reverse("grafici:nascondi_app", args=["todo"])).status_code == 302
    assert reverse("grafici:pagina_app", args=["todo"]) not in client.get(reverse("core:dashboard")).content.decode()
    assert "scheda nascosta" in client.get(reverse("grafici:pagine")).content.decode()
    client.post(reverse("grafici:nascondi_app", args=["todo"]))
    assert reverse("grafici:pagina_app", args=["todo"]) in client.get(reverse("core:dashboard")).content.decode()
    assert client.post(reverse("grafici:elimina", args=[p.pk])).status_code == 403


@pytest.mark.django_db
def test_un_grafico_dell_assistente_si_salva_in_analisi(client, superuser, attivita):
    from ai.models import Artifact, Conversazione
    c = Conversazione.objects.create(utente=superuser)
    a = Artifact.objects.create(conversazione=c, utente=superuser, tipo="grafico", titolo="Attività per stato",
                                spec={"tipo": "grafico", "vista": "todo.attivita", "per": "stato", "misura": "count",
                                      "grafico": "linee", "filtri": {}, "testo": ""},
                                dati={"serie": [["Aperta", 1], ["Fatta", 2]], "totale": 3})
    request = _richiesta(superuser, attivita)
    html = engines["django"].from_string('{% load agganci %}{% agganci "ai.artifact" %}').render({"a": a}, request=request)
    assert "Salva in Analisi" in html and f'name="artifact" value="{a.pk}"' in html and 'value="app:todo"' in html
    r = client.post(reverse("grafici:salva_da_artifact"), {"artifact": a.pk, "destinazione": "nuova", "titolo_nuova": "Vendite"})
    g = Grafico.objects.get(utente=superuser)
    assert r.status_code == 200 and "Salvato" in r.content.decode() and g.pagina.titolo == "Vendite" and g.tipo == "linee"
    assert g.spec == {"vista": "todo.attivita", "per": "stato", "misura": "count", "filtri": {}, "testo": ""}
    assert g.origine == "chat" and g.origine_url == reverse("ai:conversazione", args=[c.pk]) and dict(g.dati["serie"]) == {"Aperta": 1, "Fatta": 2}
    altro = User.objects.create_superuser("altro", "a@example.com", "x")
    client.force_login(altro)
    assert client.post(reverse("grafici:salva_da_artifact"), {"artifact": a.pk, "destinazione": ""}).status_code == 404
