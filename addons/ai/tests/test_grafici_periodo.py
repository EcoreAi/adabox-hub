"""Periodo sul grafico: Mese · Trimestre · Anno · Anno scorso e il confronto con l'anno prima, in chat e in Analisi."""
import datetime

import pytest
from django.contrib.auth.models import User

from ai import artifact, strumenti
from ai.models import Conversazione
from core import misure
from core.models import Azienda
from todo.models import Attivita

OGGI = datetime.date(2026, 11, 17)


@pytest.fixture
def contesto(db, monkeypatch):
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    for scadenza in (datetime.date(2026, 3, 10), datetime.date(2026, 3, 20), datetime.date(2025, 3, 5), datetime.date(2026, 11, 2)):
        Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo=str(scadenza), stato="aperta", scadenza=scadenza)
    return strumenti.Contesto(utente=capo, azienda=Azienda.objects.get(pk=1),
                              conversazione=Conversazione.objects.create(utente=capo, titolo="Periodo"))


def _spec(**altro):
    return {"tipo": "grafico", "vista": "todo.attivita", "per": "scadenza:mese", "misura": "count", "grafico": "barre",
            "filtri": {}, "testo": "", **altro}


def test_senza_periodo_tutti_i_mesi(contesto):
    assert sum(v for _, v in artifact.calcola(_spec(), contesto)["serie"]) == 4


def test_il_periodo_restringe_il_grafico(contesto):
    anno = artifact.calcola(_spec(periodo="anno"), contesto)
    assert sum(v for _, v in anno["serie"]) == 3 and "confronto" not in anno
    mese = artifact.calcola(_spec(periodo="mese"), contesto)
    assert [v for _, v in mese["serie"]] == [1]


def test_confronto_con_l_anno_prima_mese_per_mese(contesto):
    dati = artifact.calcola(_spec(periodo="anno", confronta=True), contesto)
    per_mese = dict(zip(dati["chiavi"], dati["confronto"]["valori"]))
    assert dati["confronto"]["etichetta"] == "Anno prima"
    assert per_mese["2026-03-01"] == 1 and per_mese["2026-11-01"] == 0     # marzo 2025 accanto a marzo 2026


def test_la_torta_non_ha_il_confronto(contesto):
    assert "confronto" not in artifact.calcola(_spec(periodo="anno", confronta=True, grafico="torta"), contesto)


def test_analisi_calcola_allo_stesso_modo(contesto):
    from core.viste.interroga import richiesta_di
    from grafici import motore
    from grafici.models import Grafico
    spec = {"vista": "todo.attivita", "per": "scadenza:mese", "misura": "count", "periodo": "anno", "confronta": True}
    req = richiesta_di(contesto.utente)
    dati = motore.dati_di(Grafico.BARRE, spec, req)
    assert sum(v for _, v in dati["serie"]) == 3
    serie = motore.serie_di(Grafico(tipo=Grafico.BARRE, titolo="x", spec=spec), dati, motore.vista_di(spec, req))
    assert serie["confronto"]["valori"] and serie["confronto"]["etichetta"] == "Anno prima"


# ---------- i pulsanti in chat ----------

def _in_chat(contesto, spec):
    from ai.models import Artifact, MessaggioChat, Turno
    turno = Turno.objects.create(conversazione=contesto.conversazione, utente=contesto.utente, stato=Turno.COMPLETATO)
    MessaggioChat.objects.create(conversazione=contesto.conversazione, ruolo=MessaggioChat.ASSISTENTE, testo="Ecco.", turno=turno)
    return Artifact.objects.create(conversazione=contesto.conversazione, turno=turno, utente=contesto.utente, azienda=contesto.azienda, tipo="grafico",
                                   titolo="Scadenze", spec=spec, dati=artifact.calcola(spec, contesto))


def test_la_chat_mostra_i_pulsanti_del_periodo(client, contesto):
    from django.urls import reverse
    a = _in_chat(contesto, _spec())
    per_stato = _in_chat(contesto, _spec(per="stato"))
    client.force_login(contesto.utente)
    html = client.get(reverse("ai:conversazione", args=[contesto.conversazione.pk])).content.decode()
    assert reverse("ai:periodo_artifact", args=[a.pk]) in html
    for etichetta in (">Mese<", ">Trimestre<", ">Anno<", ">Anno scorso<", ">Sempre<", "Confronta"):
        assert etichetta in html, etichetta
    assert reverse("ai:periodo_artifact", args=[per_stato.pk]) not in html          # senza una data: niente pulsanti


def test_scegliere_il_periodo_ricalcola_e_salva(client, contesto):
    import json
    import re
    from django.urls import reverse
    a = _in_chat(contesto, _spec())
    client.force_login(contesto.utente)
    url = reverse("ai:periodo_artifact", args=[a.pk])
    html = client.post(url, {"periodo": "anno", "confronta": "1"}, HTTP_HX_REQUEST="true").content.decode()
    a.refresh_from_db()
    assert a.spec["periodo"] == "anno" and a.spec["confronta"] is True and sum(v for _, v in a.dati["serie"]) == 3
    serie = json.loads(re.search(rf'<script id="ai-serie-{a.pk}" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert serie["confronto"]["etichetta"] == "Anno prima" and 'value="anno" aria-pressed="true"' in html
    client.post(url, {"periodo_attuale": "anno", "confronta": "1", "inverti": "1"}, HTTP_HX_REQUEST="true")   # Confronta spento
    a.refresh_from_db()
    assert a.spec["confronta"] is False and "confronto" not in a.dati
    client.post(url, {"periodo": ""}, HTTP_HX_REQUEST="true")                                          # Sempre
    a.refresh_from_db()
    assert "periodo" not in a.spec and sum(v for _, v in a.dati["serie"]) == 4
    assert client.post(url, {"periodo": "secolo"}).status_code == 400


def test_solo_il_proprietario_cambia_il_periodo(client, contesto):
    from django.urls import reverse
    a = _in_chat(contesto, _spec())
    altro = User.objects.create_user("bruno", "b@example.com", "x")
    client.force_login(altro)
    assert client.post(reverse("ai:periodo_artifact", args=[a.pk]), {"periodo": "anno"}).status_code == 404


# ---------- i pulsanti in Analisi ----------

def test_analisi_pulsanti_nella_card_e_scelta_salvata(client, contesto):
    from django.urls import reverse
    from grafici.models import Grafico
    g = Grafico.objects.create(utente=contesto.utente, titolo="Scadenze", tipo=Grafico.BARRE,
                               spec={"vista": "todo.attivita", "per": "scadenza:mese", "misura": "count"})
    client.force_login(contesto.utente)
    url = reverse("grafici:grafico_periodo", args=[g.pk])
    html = client.post(url, {"periodo": "anno", "confronta": "1"}, HTTP_HX_REQUEST="true").content.decode()
    g.refresh_from_db()
    assert g.spec["periodo"] == "anno" and g.spec["confronta"] is True and sum(v for _, v in g.dati["serie"]) == 3
    assert f'id="an-widget-{g.pk}"' in html and url in html and 'value="anno" aria-pressed="true"' in html and ">Sempre<" in html
    assert '"confronto"' in html
    torta = Grafico.objects.create(utente=contesto.utente, titolo="T", tipo=Grafico.TORTA,
                                   spec={"vista": "todo.attivita", "per": "scadenza:mese", "misura": "count"})
    html = client.post(reverse("grafici:grafico_periodo", args=[torta.pk]), {"periodo": "anno"}, HTTP_HX_REQUEST="true").content.decode()
    assert "Confronta" not in html                                                 # sulle torte niente confronto
    from django.contrib.auth.models import Permission
    altro = User.objects.create_user("bruno", "b@example.com", "x")
    altro.user_permissions.add(Permission.objects.get(codename="change_grafico"))
    client.force_login(User.objects.get(pk=altro.pk))
    assert client.post(url, {"periodo": "mese"}).status_code == 404                # il grafico è di un altro


# ---------- si vede quale periodo è (revisione finale) ----------

def test_il_titolo_automatico_segue_il_periodo_e_il_periodo_si_vede(client, contesto):
    from django.urls import reverse
    spec = {"tipo": "grafico", "grafico": "barre", "misura_aziendale": "fatturazione.fatturato", "per": "mese", "periodo": "anno"}
    a = _in_chat(contesto, spec)
    a.titolo = misure.titolo("fatturazione.fatturato", spec)
    a.save(update_fields=["titolo"])
    scritto = _in_chat(contesto, {**spec})
    scritto.titolo = "Fatture 2026 per mese"                       # un titolo scritto da Ada resta com'è
    scritto.save(update_fields=["titolo"])
    client.force_login(contesto.utente)
    html = client.post(reverse("ai:periodo_artifact", args=[a.pk]), {"periodo": "mese"}, HTTP_HX_REQUEST="true").content.decode()
    a.refresh_from_db()
    assert a.titolo == "Fatturato del mese in corso" and "del mese in corso" in html
    client.post(reverse("ai:periodo_artifact", args=[scritto.pk]), {"periodo": "mese"}, HTTP_HX_REQUEST="true")
    scritto.refresh_from_db()
    assert scritto.titolo == "Fatture 2026 per mese"
    html = client.get(reverse("ai:conversazione", args=[contesto.conversazione.pk])).content.decode()
    assert html.count("del mese in corso") >= 2                    # accanto ai due titoli


def test_analisi_scrive_il_periodo_sotto_il_titolo(client, contesto):
    from django.urls import reverse
    from grafici.models import Grafico
    g = Grafico.objects.create(utente=contesto.utente, titolo="Scadenze", tipo=Grafico.BARRE,
                               spec={"vista": "todo.attivita", "per": "scadenza:mese", "misura": "count", "periodo": "trimestre", "confronta": True})
    client.force_login(contesto.utente)
    html = client.get(reverse("grafici:grafico", args=[g.pk])).content.decode()
    assert "del trimestre in corso, a confronto con l&#x27;anno prima" in html.lower()
