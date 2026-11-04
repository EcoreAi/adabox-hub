import datetime
import json
import re

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import Azienda
from grafici.models import Grafico, Pagina


@pytest.fixture
def storia(db):
    """Attività con scadenza negli ultimi otto mesi (una nel mese scorso, due in quello prima… otto) più due nel mese in corso."""
    from core.viste.interroga import avanti_periodo, inizio_periodo
    from todo.models import Attivita
    az = Azienda.objects.get(pk=1)
    inizio = inizio_periodo(timezone.localdate(), "mese")
    for i in range(1, 9):
        for k in range(i):
            Attivita.objects.create(azienda=az, titolo=f"m{i}-{k}", scadenza=avanti_periodo(inizio, "mese", -i))
    Attivita.objects.create(azienda=az, titolo="ora1", scadenza=inizio)
    Attivita.objects.create(azienda=az, titolo="ora2", scadenza=timezone.localdate())
    return az


@pytest.fixture
def servizio(monkeypatch):
    """Un Timestral finto: mediana = ultimo valore + 1, +2, …; fascia ±2 e qualcosa."""
    from ai import specialisti

    def chiama(chiave, percorso, dati, nome):
        ultimo, h = dati["series"][0]["values"][-1], dati["horizon"]
        return {"model": "finto-timestral", "forecasts": [{"id": "serie", "quantiles": {
            "0.1": [max(ultimo - 1, 0)] * h, "0.5": [ultimo + 1 + i for i in range(h)], "0.9": [ultimo + 3 + i for i in range(h)]}}]}
    monkeypatch.setattr(specialisti, "chiama", chiama)
    monkeypatch.setattr(specialisti, "url", lambda chiave: "http://finto" if chiave == "url_forecast" else "")


def _serie(html, dom):
    m = re.search(rf'<script id="{dom}" type="application/json">(.*?)</script>', html)
    return json.loads(m.group(1)) if m else None


@pytest.mark.django_db
def test_previsione_dal_costruttore_solo_con_il_servizio(client, superuser, storia, servizio, monkeypatch):
    from ai import specialisti
    html = client.get(reverse("grafici:costruttore")).content.decode()
    assert 'value="previsione"' in html
    html = client.get(reverse("grafici:costruttore") + "?vista=todo.attivita&tipo=previsione&data=scadenza&periodo=mese&orizzonte=6").content.decode()
    serie = _serie(html, "wd-anteprima")
    assert serie["tipo"] == "previsione" and len(serie["futuro"]) == 6 and len(serie["storico"]) == 8 and serie["storico"][-1][1] == 1
    assert serie["futuro"][0][2] == 2 and 'name="orizzonte"' in html
    r = client.post(reverse("grafici:costruttore"), {"vista": "todo.attivita", "tipo": "previsione", "misura": "count", "data": "scadenza",
                                                     "periodo": "mese", "orizzonte": "3", "titolo": "Attività previste",
                                                     "destinazione": "nuova", "titolo_nuova": "Previsioni", "aggiorna_ogni": "24"})
    g = Grafico.objects.get(utente=superuser)
    assert r.status_code == 302 and g.tipo == "previsione" and g.aggiorna_ogni == 24
    assert g.spec == {"vista": "todo.attivita", "misura": "count", "data": "scadenza", "per": "mese", "orizzonte": 3}
    html = client.get(reverse("grafici:pagina", args=[g.pagina.pk])).content.decode()
    s = _serie(html, f"wd-g-{g.pk}")
    assert s["tipo"] == "previsione" and len(s["futuro"]) == 3 and s["modello"] == "finto-timestral" and "previsione di numero a 3 mesi" in html
    testo = client.get(reverse("grafici:grafico_csv", args=[g.pk])).content.decode("utf-8-sig")
    assert testo.startswith("Periodo;Valore;Previsione 10 %")
    html = client.get(reverse("grafici:grafico_costruttore", args=[g.pk])).content.decode()
    assert 'value="3" selected' in html and 'value="24" selected' in html and 'value="scadenza" selected' in html
    # senza servizio: la previsione sparisce dai tipi; il grafico salvato tiene l'ultima istantanea e segnala l'errore
    monkeypatch.setattr(specialisti, "url", lambda chiave: "")

    def giu(*a, **k):
        raise specialisti.ErroreStrumento("Il servizio di previsione non è configurato.")
    monkeypatch.setattr(specialisti, "chiama", giu)
    assert 'value="previsione"' not in client.get(reverse("grafici:costruttore")).content.decode()
    Grafico.objects.filter(pk=g.pk).update(aggiornato=timezone.now() - datetime.timedelta(days=2))
    html = client.get(reverse("grafici:pagina", args=[g.pagina.pk])).content.decode()
    assert "an-errore" in html and "non è configurato" in html and len(_serie(html, f"wd-g-{g.pk}")["futuro"]) == 3


@pytest.mark.django_db
def test_gli_strumenti_di_ada_leggono_le_pagine_e_salvano_grafici_con_conferma(superuser, storia):
    from ai import strumenti
    from ai.models import Artifact, Conversazione
    from grafici import ai as analisi
    c = Conversazione.objects.create(utente=superuser)
    ctx = strumenti.Contesto(utente=superuser, azienda=storia, conversazione=c)
    nomi = {s.nome for s in strumenti.disponibili(superuser)}
    assert {"analisi_pagine", "analisi_leggi_pagina", "analisi_salva_grafico", "analisi_crea_pagina"} <= nomi
    assert analisi.analisi_pagine(ctx).startswith("Nessuna pagina")
    # una pagina: anteprima, poi la conferma la crea; due volte no
    assert "Direzione" in analisi.anteprima_crea_pagina(ctx, "Direzione")["titolo"]
    p = Pagina.objects.get(pk=analisi.crea_pagina(ctx, "Direzione")["pagina"])
    with pytest.raises(strumenti.ErroreStrumento):
        analisi.anteprima_crea_pagina(ctx, "direzione")
    # un grafico dalla query, nella pagina indicata per titolo
    a = analisi.anteprima_salva(ctx, vista="todo.attivita", per="stato", tipo="torta", pagina="Direzione")
    assert a["dettagli"][2]["dopo"] == "pagina «Direzione»" and "Numero per stato" in a["dettagli"][0]["dopo"]
    r = analisi.salva_grafico(ctx, vista="todo.attivita", per="stato", tipo="torta", pagina="Direzione")
    g = Grafico.objects.get(utente=superuser)
    assert g.pagina == p and g.tipo == "torta" and g.origine == "chat" and g.origine_url == reverse("ai:conversazione", args=[c.pk])
    assert r["url"] == reverse("grafici:pagina", args=[p.pk]) and g.dati["serie"]
    # un KPI in una pagina che non c'è ancora: si crea al volo
    assert analisi.anteprima_salva(ctx, vista="todo.attivita", tipo="kpi", data="scadenza", pagina="Vendite")["dettagli"][2]["dopo"] == "pagina nuova «Vendite»"
    analisi.salva_grafico(ctx, vista="todo.attivita", tipo="kpi", data="scadenza", periodo="mese", pagina="Vendite", titolo="Scadenze")
    assert Pagina.objects.filter(utente=superuser, titolo="Vendite").exists() and Grafico.objects.get(titolo="Scadenze").dati["valore"] == 2
    # il grafico appena disegnato in chat, in libreria
    art = Artifact.objects.create(conversazione=c, utente=superuser, tipo="grafico", titolo="Per stato",
                                  spec={"tipo": "grafico", "vista": "todo.attivita", "per": "stato", "misura": "count", "grafico": "linee"}, dati={})
    assert analisi.anteprima_salva(ctx, artifact=art.pk)["dettagli"][2]["dopo"].startswith("libreria")
    g2 = Grafico.objects.get(pk=analisi.salva_grafico(ctx, artifact=art.pk)["grafico"])
    assert g2.pagina is None and g2.tipo == "linee" and g2.spec == {"vista": "todo.attivita", "per": "stato", "misura": "count"} and g2.titolo == "Per stato"
    # lettura della pagina ed elenco
    letto = analisi.analisi_leggi_pagina(ctx, "Direzione")
    assert letto["pagina"] == "Analisi: Direzione" and letto["grafici"][0]["dati"] and letto["url"] == reverse("grafici:pagina", args=[p.pk])
    assert [x["titolo"] for x in analisi.analisi_pagine(ctx)] == ["Direzione", "Vendite"]
    for argomenti in ({"vista": "todo.inesistente", "per": "stato"}, {"vista": "todo.attivita", "tipo": "barre"}, {"artifact": 999},
                      {"vista": "todo.attivita", "tipo": "previsione"}):
        with pytest.raises(strumenti.ErroreStrumento):
            analisi.anteprima_salva(ctx, **argomenti)
    with pytest.raises(strumenti.ErroreStrumento):
        analisi.analisi_leggi_pagina(ctx, "Boh")


@pytest.mark.django_db
def test_il_worker_ricalcola_solo_i_grafici_scaduti(client, superuser, storia):
    from grafici import lavori
    p = Pagina.objects.create(utente=superuser, titolo="P")
    spec = {"vista": "todo.attivita", "per": "stato"}
    scaduto = Grafico.objects.create(utente=superuser, pagina=p, titolo="A", spec=spec, aggiorna_ogni=1,
                                     aggiornato=timezone.now() - datetime.timedelta(hours=2))
    fresco = Grafico.objects.create(utente=superuser, pagina=p, titolo="B", spec=spec, aggiorna_ogni=24, aggiornato=timezone.now())
    manuale = Grafico.objects.create(utente=superuser, pagina=p, titolo="C", spec=spec)
    rotto = Grafico.objects.create(utente=superuser, pagina=p, titolo="D", spec={"vista": "todo.nope", "per": "stato"}, aggiorna_ogni=1)
    assert lavori.aggiorna_scaduti() == 1
    for g in (scaduto, fresco, manuale, rotto):
        g.refresh_from_db()
    assert dict(scaduto.dati["serie"])["Aperta"] == 38 and scaduto.aggiornato > timezone.now() - datetime.timedelta(minutes=1)
    assert fresco.dati == {} and manuale.dati == {} and manuale.aggiornato is None
    assert rotto.dati == {} and rotto.aggiornato is not None               # provato: riproverà alla prossima scadenza
    assert lavori.aggiorna_scaduti() == 0
    # askAda sulle pagine di Analisi suggerisce il confronto col periodo prima
    html = client.get(reverse("askada:apri") + "?analisi=1&url=/grafici/pagina/1/&titolo=Analisi").content.decode()
    assert "Cosa è cambiato rispetto al periodo prima?" in html
