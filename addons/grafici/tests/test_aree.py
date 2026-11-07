"""La dashboard di un'area di lavoro dell'assistente: una pagina di Analisi legata all'area, che vedono e dispongono i
suoi membri. Ci si salvano grafici e tabelle delle chat dell'area (anche da Ada); chi non è membro non la vede."""
import json

import pytest
from django.contrib.auth.models import User
from django.template import engines
from django.test import RequestFactory
from django.urls import reverse

from core.models import Azienda
from grafici import motore
from grafici.models import Grafico, Pagina


@pytest.fixture
def area(db, superuser):
    from ai import aree
    from ai.models import Conversazione, ProgettoChat
    from todo.models import Attivita
    az = Azienda.objects.get(pk=1)
    Attivita.objects.create(azienda=az, titolo="Alfa")
    Attivita.objects.create(azienda=az, titolo="Beta", stato=Attivita.FATTA)
    bruno = User.objects.create_superuser("bruno", "b@example.com", "x")
    a = ProgettoChat.objects.create(utente=superuser, azienda=az, nome="Sviluppo Adabox")
    aree.imposta_membri(a, [bruno])
    chat = Conversazione.objects.create(utente=superuser, progetto=a, titolo="Stato lavori")
    return {"area": a, "chat": chat, "bruno": bruno, "azienda": az}


def _artifact(s, tipo="grafico"):
    from ai.models import Artifact
    if tipo == "grafico":
        spec = {"tipo": "grafico", "vista": "todo.attivita", "per": "stato", "misura": "count", "grafico": "barre", "filtri": {}, "testo": ""}
    else:
        spec = {"tipo": "tabella", "vista": "todo.attivita", "testo": "", "filtri": {}, "ordina": "titolo", "campi": [], "limite": 50}
    return Artifact.objects.create(conversazione=s["chat"], utente=s["chat"].utente, azienda=s["azienda"], tipo=tipo,
                                   titolo="Attività per stato" if tipo == "grafico" else "Elenco attività", spec=spec)


def test_dalla_chat_dell_area_alla_sua_dashboard(client, superuser, area):
    grafico, tabella = _artifact(area), _artifact(area, "tabella")
    request = RequestFactory().get("/")
    request.user, request.azienda = superuser, area["azienda"]
    html = engines["django"].from_string('{% load agganci %}{% agganci "ai.artifact" %}').render({"a": tabella}, request=request)
    scelte = html.split('name="destinazione"', 1)[1]
    assert scelte.index(f'value="area:{area["area"].pk}"') < scelte.index('value="nuova"')      # prima di tutto l'area
    assert "Dashboard dell&#x27;area «Sviluppo Adabox»" in html and "Aggiungi alla dashboard dell'area" in html
    for a in (grafico, tabella):
        r = client.post(reverse("grafici:salva_da_artifact"), {"artifact": a.pk, "destinazione": f"area:{area['area'].pk}"})
        assert reverse("grafici:pagina_area", args=[area["area"].pk]) in r.content.decode()
    p = Pagina.objects.get(area=area["area"].pk)
    assert p.utente == superuser and p.titolo == "Dashboard · Sviluppo Adabox" and len(p.id_widget) == 2
    assert Grafico.objects.get(titolo="Elenco attività").tipo == Grafico.TABELLA

    client.force_login(area["bruno"])                                          # un membro la vede, con le due card
    pagina = client.get(reverse("grafici:pagina_area", args=[area["area"].pk])).content.decode()
    assert "Attività per stato" in pagina and "Elenco attività" in pagina and ">Alfa</a>" in pagina and "Beta" in pagina
    assert "Sviluppo Adabox" in pagina and "an-schede" not in pagina and "Elimina pagina" not in pagina
    t = Grafico.objects.get(titolo="Elenco attività")
    r = client.post(reverse("grafici:layout_area", args=[area["area"].pk]), json.dumps({"widget": [{"id": t.id_widget, "w": 4}]}),
                    content_type="application/json")
    assert r.status_code == 200 and Pagina.objects.get(pk=p.pk).id_widget == [t.id_widget]   # e la dispone

    assert client.get(reverse("grafici:pagina", args=[p.pk])).url == reverse("grafici:pagina_area", args=[area["area"].pk])
    assert "Dashboard · Sviluppo Adabox" not in client.get(reverse("grafici:pagine")).content.decode()   # non tra le pagine


def test_chi_non_e_membro_non_la_vede(client, superuser, area):
    estraneo = User.objects.create_superuser("carla", "c@example.com", "x")
    client.force_login(estraneo)
    assert client.get(reverse("grafici:pagina_area", args=[area["area"].pk])).status_code == 404
    assert not Pagina.objects.filter(area=area["area"].pk).exists()
    g = Grafico.objects.create(utente=estraneo, titolo="Mio", spec={"vista": "todo.attivita", "per": "stato"})
    with pytest.raises(ValueError):
        motore.metti_in(estraneo, f"area:{area['area'].pk}", g, azienda=area["azienda"])
    assert client.post(reverse("grafici:layout_area", args=[area["area"].pk]), "{}", content_type="application/json").status_code == 404


def test_ada_salva_e_legge_la_dashboard_dell_area(superuser, area):
    from ai.strumenti import Contesto
    from grafici import ai as strumenti_analisi
    a = _artifact(area, "tabella")
    ctx = Contesto(utente=superuser, azienda=area["azienda"], conversazione=area["chat"])
    dove = f"area:{area['area'].pk}"
    anteprima = strumenti_analisi.anteprima_salva(ctx, artifact=a.pk, pagina=dove)
    assert {"campo": "Dove", "dopo": "dashboard dell'area «Sviluppo Adabox»"} in anteprima["dettagli"]
    esito = strumenti_analisi.salva_grafico(ctx, artifact=a.pk, pagina=dove)
    assert esito["url"] == reverse("grafici:pagina_area", args=[area["area"].pk])
    letta = strumenti_analisi.analisi_leggi_pagina(ctx, dove)
    assert "Elenco attività" in json.dumps(letta, ensure_ascii=False)
    with pytest.raises(Exception, match="Area di lavoro"):
        strumenti_analisi.anteprima_salva(ctx, artifact=a.pk, pagina="area:999")


def test_link_alla_dashboard_dall_area(client, superuser, area):
    pagina = client.get(reverse("ai:progetto", args=[area["area"].pk])).content.decode()
    assert reverse("grafici:pagina_area", args=[area["area"].pk]) in pagina
    albero = client.get(reverse("ai:albero_progetto", args=[area["area"].pk])).content.decode()
    assert "ai-albero-dashboard" in albero
