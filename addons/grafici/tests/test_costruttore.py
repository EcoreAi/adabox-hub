import datetime
import json
import re

import pytest
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from core.models import Azienda
from core.viste import interroga
from grafici.tests.aiuti import in_pagina
from grafici.models import Grafico, Pagina


@pytest.fixture
def attivita(db):
    """Quattro attività: due con scadenza in questo mese, una nel mese scorso, una senza."""
    from todo.models import Attivita
    az = Azienda.objects.get(pk=1)
    oggi = timezone.localdate()
    inizio_mese = oggi.replace(day=1)
    Attivita.objects.create(azienda=az, titolo="Alfa", scadenza=oggi)
    Attivita.objects.create(azienda=az, titolo="Beta", scadenza=inizio_mese, stato=Attivita.FATTA)
    Attivita.objects.create(azienda=az, titolo="Gamma", scadenza=inizio_mese - datetime.timedelta(days=1), stato=Attivita.FATTA)
    Attivita.objects.create(azienda=az, titolo="Delta")
    return az


def _serie(html, dom):
    m = re.search(rf'<script id="{dom}" type="application/json">(.*?)</script>', html)
    return json.loads(m.group(1)) if m else None


def _richiesta(utente, azienda):
    request = RequestFactory().get("/")
    request.user, request.azienda = utente, azienda
    return request


@pytest.mark.django_db
def test_costruttore_anteprima_drill_down_salvataggio_e_modifica(client, superuser, attivita):
    html = client.get(reverse("grafici:costruttore")).content.decode()
    assert 'name="vista"' in html and 'value="todo.attivita"' in html and "Scegli una vista per cominciare" in html
    # con la vista scelta: raggruppamento suggerito (stato), filtri della lista, anteprima disegnata
    html = client.get(reverse("grafici:costruttore") + "?vista=todo.attivita&tipo=barre&f_stato=fatta").content.decode()
    serie = _serie(html, "wd-anteprima")
    assert serie["etichette"] == ["Fatta"] and serie["valori"] == [2.0] and 'name="f_stato"' in html and 'value="fatta" selected' in html
    assert serie["link"] == [reverse("todo:attivita_lista") + "?f_stato=fatta"]            # stato è tra i filtri della lista
    html = client.get(reverse("grafici:costruttore") + "?vista=todo.attivita&tipo=linee&per=scadenza:mese").content.decode()
    serie = _serie(html, "wd-anteprima")
    assert serie["tipo"] == "linee" and serie["link"] == [] and sum(serie["valori"]) == 3        # scadenza non filtra la lista: nessun link
    # salvataggio in una pagina nuova, titolo automatico
    r = client.post(reverse("grafici:costruttore"), {"vista": "todo.attivita", "per": "stato", "misura": "count", "tipo": "torta",
                                                     "f_stato": "fatta", "massimo": "10", "ordine": "valore", "titolo": "",
                                                     "destinazione": "nuova", "titolo_nuova": "Operativo"})
    g = Grafico.objects.get(utente=superuser)
    operativo = Pagina.objects.get(titolo="Operativo")
    assert r.status_code == 302 and g.id_widget in operativo.id_widget and g.tipo == "torta" and g.origine == "costruttore"
    assert g.spec == {"vista": "todo.attivita", "misura": "count", "per": "stato", "massimo": 10, "ordine": "valore", "lista": {"f_stato": "fatta"}}
    assert "Numero per stato" in g.titolo and dict(g.dati["serie"]) == {"Fatta": 2} and g.aggiornato is not None
    # modifica: il form si ripresenta con la query del grafico, il salvataggio la cambia
    html = client.get(reverse("grafici:grafico_costruttore", args=[g.pk])).content.decode()
    assert 'value="todo.attivita" selected' in html and 'value="fatta" selected' in html and "Salva le modifiche" in html
    r = client.post(reverse("grafici:grafico_costruttore", args=[g.pk]), {"vista": "todo.attivita", "per": "assegnatario", "misura": "count",
                                                                          "tipo": "barre", "massimo": "30", "titolo": "Per persona"})
    g.refresh_from_db()
    assert r.status_code == 302 and g.spec == {"vista": "todo.attivita", "misura": "count", "per": "assegnatario"} and g.titolo == "Per persona"
    # vista non accessibile: niente salvato, il form torna con l'errore
    r = client.post(reverse("grafici:costruttore"), {"vista": "todo.inesistente", "per": "x", "tipo": "barre"})
    assert r.status_code == 200 and Grafico.objects.count() == 1
    # il costruttore si raggiunge dalla pagina e dalla card
    html = client.get(reverse("grafici:pagina", args=[operativo.pk])).content.decode()
    assert reverse("grafici:costruttore") + "?destinazione=" + str(operativo.pk) in html and reverse("grafici:grafico_costruttore", args=[g.pk]) in html


@pytest.mark.django_db
def test_kpi_con_delta_sparkline_e_anteprima(client, superuser, attivita):
    request = _richiesta(superuser, attivita)
    r = interroga.kpi({"vista": "todo.attivita", "misura": "count", "data": "scadenza", "periodo": "mese"}, request)
    assert (r["valore"], r["precedente"], r["delta"]) == (2, 1, 100.0) and len(r["storico"]) == 12
    assert r["storico"][-1][1] == 2 and r["storico"][-2][1] == 1 and r["periodo"] == "mese"
    r = interroga.kpi({"vista": "todo.attivita", "misura": "count"}, request)
    assert r["valore"] == 4 and r["delta"] is None and r["storico"] == []
    opzioni = interroga.opzioni_vista(interroga.vista_per_nome("todo.attivita", request))
    assert ("scadenza", "scadenza") in opzioni["date"] and opzioni["raggruppamenti"][0][0] == "stato" and opzioni["misure"][0][0] == "count"
    # il widget KPI: numero, delta, sparkline, largo una colonna
    p = Pagina.objects.create(utente=superuser, titolo="P")
    g = in_pagina(p, utente=superuser, titolo="Scadenze del mese", tipo="kpi",
                               spec={"vista": "todo.attivita", "misura": "count", "data": "scadenza", "periodo": "mese"})
    html = client.get(reverse("grafici:pagina", args=[p.pk])).content.decode()
    assert "an-kpi" in html and "+100 %" in html and "questo mese" in html and f'data-id="g:{g.pk}" data-w="1"' in html
    serie = _serie(html, f"wd-g-{g.pk}")
    assert serie["tipo"] == "kpi" and serie["valore_testo"] == "2" and len(serie["valori"]) == 12
    # anteprima KPI dal costruttore, CSV e pagina in grande
    html = client.get(reverse("grafici:costruttore") + "?vista=todo.attivita&tipo=kpi&data=scadenza&periodo=mese").content.decode()
    assert "an-kpi" in html and "+100 %" in html and 'name="periodo"' in html
    testo = client.get(reverse("grafici:grafico_csv", args=[g.pk])).content.decode("utf-8-sig")
    assert testo.startswith("Periodo;Valore") and "Attuale;2" in testo
    html = client.get(reverse("grafici:grafico", args=[g.pk])).content.decode()
    assert "an-kpi" in html and "Modifica la query" in html
