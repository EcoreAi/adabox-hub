"""Grafici cliccabili in chat: ogni punto porta il link ai record che lo formano, oppure niente se l'elenco non sa
filtrarli (un link che mostra altri record sarebbe una bugia)."""
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from ai import artifact, strumenti
from ai.models import Artifact, Conversazione
from core.models import Azienda
from todo.models import Attivita


@pytest.fixture
def contesto(db):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    return strumenti.Contesto(utente=capo, azienda=Azienda.objects.get(pk=1),
                              conversazione=Conversazione.objects.create(utente=capo, titolo="Grafici"))


def _attivita(stato, n=1, **campi):
    for i in range(n):
        Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo=f"{stato} {i}", stato=stato, **campi)


def _link(r):
    return Artifact.objects.get(pk=r["artifact"]).dati["link"]


def test_grafico_per_stato_ha_un_link_per_barra(contesto):
    _attivita("aperta", 3)
    _attivita("fatta", 1)
    r = artifact.grafico(contesto, vista="todo.attivita", per="stato")
    lista = reverse("todo:attivita_lista")
    assert [e for e, _ in r["serie"]] == ["Aperta", "Fatta"]
    assert _link(r) == [lista + "?f_stato=aperta", lista + "?f_stato=fatta"]


def test_primi_altro_senza_link(contesto):
    _attivita("aperta", 3)
    _attivita("fatta", 2)
    _attivita("in_corso", 1)
    r = artifact.grafico(contesto, vista="todo.attivita", per="stato", primi=1)
    assert [e for e, _ in r["serie"]] == ["Aperta", "Altro"]
    assert _link(r) == [reverse("todo:attivita_lista") + "?f_stato=aperta", None]


def test_gruppo_senza_valore_non_sposta_gli_altri_link(contesto):
    _attivita("aperta", 2)
    _attivita("aperta", 1, assegnatario=contesto.utente)
    r = artifact.grafico(contesto, vista="todo.attivita", per="assegnatario")
    coppie = list(zip(r["serie"], _link(r)))
    assert len(coppie) == 2
    for (etichetta, valore), link in coppie:                              # ogni link resta accanto al suo punto
        if valore == 1:
            assert link == reverse("todo:attivita_lista") + f"?f_assegnatario={contesto.utente.pk}"
        else:
            assert link is None                                           # il gruppo «nessuno» non ha link


def test_campo_che_la_lista_non_filtra_niente_link(contesto):
    import datetime
    _attivita("aperta", 2, scadenza=datetime.date(2026, 11, 3))
    r = artifact.grafico(contesto, vista="todo.attivita", per="scadenza:mese", tipo="linee")
    assert r["serie"] and _link(r) == [None] * len(r["serie"])


def test_aggiorna_ricalcola_i_link(contesto):
    _attivita("aperta", 1)
    r = artifact.grafico(contesto, vista="todo.attivita", per="stato")
    a = Artifact.objects.get(pk=r["artifact"])
    _attivita("fatta", 1)
    assert len(artifact.ricalcola(a)["link"]) == 2


# ---------- la chat e la pagina del grafico ----------

def _in_chat(contesto, **opzioni):
    """Un grafico sotto una risposta di Ada, come lo lascia un turno."""
    from ai.models import MessaggioChat, Turno
    contesto.turno = Turno.objects.create(conversazione=contesto.conversazione, utente=contesto.utente, stato=Turno.COMPLETATO)
    MessaggioChat.objects.create(conversazione=contesto.conversazione, ruolo=MessaggioChat.ASSISTENTE, testo="Ecco.",
                                 turno=contesto.turno)
    return Artifact.objects.get(pk=artifact.grafico(contesto, vista="todo.attivita", per="stato", **opzioni)["artifact"])


def _serie_nella_pagina(html, pk):
    import json
    import re
    trovato = re.search(rf'<script id="ai-serie-{pk}" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(trovato.group(1)) if trovato else None


def test_la_chat_disegna_il_grafico_cliccabile(client, contesto):
    _attivita("aperta", 2)
    a = _in_chat(contesto)
    client.force_login(contesto.utente)
    html = client.get(reverse("ai:conversazione", args=[contesto.conversazione.pk])).content.decode()
    assert f'data-grafico="ai-serie-{a.pk}"' in html and "core/grafici.js" in html and "chart.umd.js" in html
    serie = _serie_nella_pagina(html, a.pk)
    assert serie["tipo"] == "barre" and serie["etichette"] == ["Aperta"] and serie["valori"] == [2]
    assert serie["link"] == [reverse("todo:attivita_lista") + "?f_stato=aperta"]
    assert "<noscript>" in html and "<svg" in html                       # senza JavaScript resta il disegno di prima


def test_aggiorna_ridisegna_con_i_link(client, contesto):
    _attivita("aperta", 1)
    a = _in_chat(contesto)
    _attivita("fatta", 1)
    client.force_login(contesto.utente)
    html = client.post(reverse("ai:aggiorna_artifact", args=[a.pk]), HTTP_HX_REQUEST="true").content.decode()
    assert html.count(f'data-grafico="ai-serie-{a.pk}"') == 1 and html.count(f'id="ai-serie-{a.pk}"') == 1
    assert len(_serie_nella_pagina(html, a.pk)["link"]) == 2


def test_grafico_salvato_prima_dei_link_si_disegna_senza_clic(client, contesto):
    _attivita("aperta", 1)
    a = _in_chat(contesto)
    a.dati = {k: v for k, v in a.dati.items() if k != "link"}
    a.save(update_fields=["dati"])
    client.force_login(contesto.utente)
    html = client.get(reverse("ai:conversazione", args=[contesto.conversazione.pk])).content.decode()
    assert _serie_nella_pagina(html, a.pk)["link"] == []


def test_previsione_resta_svg(client, contesto):
    from ai.models import MessaggioChat, Turno
    turno = Turno.objects.create(conversazione=contesto.conversazione, utente=contesto.utente, stato=Turno.COMPLETATO)
    MessaggioChat.objects.create(conversazione=contesto.conversazione, ruolo=MessaggioChat.ASSISTENTE, testo="Ecco.", turno=turno)
    a = Artifact.objects.create(conversazione=contesto.conversazione, turno=turno, utente=contesto.utente, tipo=Artifact.GRAFICO,
                                titolo="Previsione", spec={"tipo": "grafico", "grafico": "previsione"},
                                dati={"storico": [["ott", 3], ["nov", 4]], "futuro": [["dic", 3, 4, 5]]})
    client.force_login(contesto.utente)
    html = client.get(reverse("ai:conversazione", args=[contesto.conversazione.pk])).content.decode()
    assert f"ai-serie-{a.pk}" not in html and "<svg" in html


def test_pagina_del_grafico_cliccabile(client, contesto):
    _attivita("aperta", 1)
    a = _in_chat(contesto, tipo="torta")
    _attivita("fatta", 1)
    client.force_login(contesto.utente)
    html = client.get(reverse("ai:artifact", args=[a.pk])).content.decode()
    serie = _serie_nella_pagina(html, a.pk)
    assert serie["tipo"] == "torta" and len(serie["link"]) == 2    # i dati di oggi
    assert "core/grafici.js" in html and "chart.umd.js" in html


# ---------- i filtri del grafico nel link (revisione finale) ----------

def _vista_finta(*filtri):
    from types import SimpleNamespace
    return SimpleNamespace(list_filter=list(filtri), model=Attivita, url=lambda nome: "/todo/attivita/")


def _parametri(link):
    from urllib.parse import parse_qs, urlsplit
    return {k: v[0] for k, v in parse_qs(urlsplit(link).query).items()}


def test_il_link_porta_i_filtri_del_grafico():
    from core.viste.interroga import link_gruppo
    vista = _vista_finta("stato", "assegnatario", "scadenza")
    spec = {"per": "assegnatario", "testo": "rossi", "filtri": {"stato": "aperta", "scadenza__gte": "2026-01-01",
                                                                   "scadenza__lte": "2026-12-31"}}
    assert _parametri(link_gruppo(vista, spec, 7)) == {"f_assegnatario": "7", "q": "rossi", "f_stato": "aperta",
                                                       "f_scadenza_da": "2026-01-01", "f_scadenza_a": "2026-12-31"}
    anno = link_gruppo(vista, {"per": "stato", "filtri": {"scadenza__year": 2026}}, "aperta")
    assert _parametri(anno) == {"f_stato": "aperta", "f_scadenza_da": "2026-01-01", "f_scadenza_a": "2026-12-31"}
    giorno = link_gruppo(vista, {"per": "stato", "filtri": {"scadenza": "2026-11-03"}}, "aperta")
    assert _parametri(giorno)["f_scadenza_da"] == _parametri(giorno)["f_scadenza_a"] == "2026-11-03"
    # il mese del gruppo dentro l'anno del filtro: vale l'intersezione
    mese = link_gruppo(vista, {"per": "scadenza:mese", "filtri": {"scadenza__gte": "2026-11-10"}}, "2026-11-01")
    assert _parametri(mese) == {"f_scadenza_da": "2026-11-10", "f_scadenza_a": "2026-11-30"}


def test_un_filtro_che_la_lista_non_sa_applicare_toglie_il_link():
    from core.viste.interroga import link_gruppo
    vista = _vista_finta("stato", "assegnatario", "scadenza")
    for filtri in ({"titolo__icontains": "x"}, {"stato__in": ["aperta", "fatta"]}, {"descrizione": "x"},
                   {"scadenza__gt": "2026-01-01"}, {"assegnatario__username": "capo"}):
        assert link_gruppo(vista, {"per": "stato", "filtri": filtri}, "aperta") is None, filtri
    assert link_gruppo(vista, {"per": "stato", "aziende": "tutte"}, "aperta") is None


def test_filtri_scritti_come_testo_json():
    from core.viste.interroga import link_gruppo
    vista = _vista_finta("stato", "assegnatario")
    assert _parametri(link_gruppo(vista, {"per": "assegnatario", "filtri": '{"stato": "fatta"}'}, 3)) == \
        {"f_assegnatario": "3", "f_stato": "fatta"}
