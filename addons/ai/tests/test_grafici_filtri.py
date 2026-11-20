"""Filtri sul grafico in chat: «Filtra» apre i filtri del grafico con i valori presenti; la scelta resta come etichetta
con la × e il grafico si ricalcola lì dov'è."""
import json
import re

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from ai import artifact, strumenti
from ai.models import Artifact, Conversazione, MessaggioChat, Turno
from core.models import Azienda
from todo.models import Attivita


@pytest.fixture
def scena(db, client):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    bruno = User.objects.create_user("bruno", "b@example.com", "x", first_name="Bruno")
    for stato, persona, n in (("aperta", bruno, 3), ("aperta", capo, 1), ("fatta", bruno, 2)):
        for i in range(n):
            Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo=f"{stato} {i}", stato=stato, assegnatario=persona)
    c = Conversazione.objects.create(utente=capo, titolo="Filtri")
    contesto = strumenti.Contesto(utente=capo, azienda=Azienda.objects.get(pk=1), conversazione=c)
    turno = Turno.objects.create(conversazione=c, utente=capo, stato=Turno.COMPLETATO)
    MessaggioChat.objects.create(conversazione=c, ruolo=MessaggioChat.ASSISTENTE, testo="Ecco.", turno=turno)
    spec = {"tipo": "grafico", "vista": "todo.attivita", "per": "stato", "misura": "count", "grafico": "barre", "filtri": {}, "testo": ""}
    a = Artifact.objects.create(conversazione=c, turno=turno, utente=capo, azienda=contesto.azienda, tipo="grafico",
                                titolo="Attività per stato", spec=spec, dati=artifact.calcola(spec, contesto))
    client.force_login(capo)
    return {"capo": capo, "bruno": bruno, "a": a, "c": c}


def _serie(html, pk):
    return json.loads(re.search(rf'<script id="ai-serie-{pk}" type="application/json">(.*?)</script>', html, re.S).group(1))


def test_la_chat_ha_filtra_anche_senza_periodo(client, scena):
    html = client.get(reverse("ai:conversazione", args=[scena["c"].pk])).content.decode()
    assert reverse("ai:filtri_artifact", args=[scena["a"].pk]) in html and "Filtra" in html


def test_il_pannello_mostra_i_filtri_con_i_valori(client, scena):
    html = client.get(reverse("ai:filtri_artifact", args=[scena["a"].pk])).content.decode()
    assert "Assegnatario" in html and f'value="{scena["bruno"].pk}"' in html and ">bruno<" in html
    assert html.index(f'value="{scena["bruno"].pk}"') < html.index(f'value="{scena["capo"].pk}"')    # dal più grande
    assert reverse("ai:filtro_artifact", args=[scena["a"].pk]) in html


def test_scegliere_e_togliere_un_filtro(client, scena):
    a, url = scena["a"], reverse("ai:filtro_artifact", args=[scena["a"].pk])
    html = client.post(url, {"campo": "assegnatario", "chiave": str(scena["capo"].pk)}, HTTP_HX_REQUEST="true").content.decode()
    a.refresh_from_db()
    assert a.spec["scelti"]["assegnatario"]["chiave"] == scena["capo"].pk and dict(a.dati["serie"]) == {"Aperta": 1}
    assert "Assegnatario: capo" in html and f"f_assegnatario={scena['capo'].pk}" in _serie(html, a.pk)["link"][0]
    assert 'name="chiave" value=""' in html                                      # la × per toglierlo
    client.post(url, {"campo": "assegnatario", "chiave": ""}, HTTP_HX_REQUEST="true")
    a.refresh_from_db()
    assert "scelti" not in a.spec and dict(a.dati["serie"]) == {"Aperta": 4, "Fatta": 2}
    assert client.post(url, {"campo": "titolo", "chiave": "x"}).status_code == 400


def test_solo_il_proprietario(client, scena):
    client.force_login(scena["bruno"])
    assert client.get(reverse("ai:filtri_artifact", args=[scena["a"].pk])).status_code == 404
    assert client.post(reverse("ai:filtro_artifact", args=[scena["a"].pk]), {"campo": "assegnatario", "chiave": "1"}).status_code == 404


def test_analisi_filtra_nella_card_e_lo_scrive_sotto_il_titolo(client, scena):
    from django.contrib.auth.models import Permission
    from grafici.models import Grafico
    g = Grafico.objects.create(utente=scena["capo"], titolo="Attività", tipo=Grafico.BARRE,
                               spec={"vista": "todo.attivita", "per": "stato", "misura": "count"})
    html = client.get(reverse("grafici:grafico_filtri", args=[g.pk])).content.decode()
    assert "Assegnatario" in html and f'value="{scena["bruno"].pk}"' in html
    url = reverse("grafici:grafico_filtro", args=[g.pk])
    html = client.post(url, {"campo": "assegnatario", "chiave": str(scena["bruno"].pk)}, HTTP_HX_REQUEST="true").content.decode()
    g.refresh_from_db()
    assert g.spec["scelti"]["assegnatario"]["chiave"] == scena["bruno"].pk and dict(g.dati["serie"]) == {"Aperta": 3, "Fatta": 2}
    assert f'id="an-widget-{g.pk}"' in html and "Assegnatario: bruno" in html and reverse("grafici:grafico_filtri", args=[g.pk]) in html
    pagina = client.get(reverse("grafici:grafico", args=[g.pk])).content.decode()
    assert "Assegnatario: bruno" in pagina                                       # anche nella pagina «Apri in grande»
    altro = User.objects.create_user("carla", "c@example.com", "x")
    altro.user_permissions.add(Permission.objects.get(codename="change_grafico"))
    client.force_login(User.objects.get(pk=altro.pk))
    assert client.post(url, {"campo": "assegnatario", "chiave": ""}).status_code == 404


# ---------- revisione finale ----------

def test_la_chat_non_cerca_le_viste_per_disegnare_filtra(client, scena, monkeypatch):
    """Disegnare la chat non deve rifare la ricerca delle viste per ogni grafico (lenta): il pannello la fa al clic."""
    from core.viste import interroga
    chiamate = []
    originale = interroga.vista_per_nome
    monkeypatch.setattr(interroga, "vista_per_nome", lambda *a, **k: chiamate.append(a) or originale(*a, **k))
    html = client.get(reverse("ai:conversazione", args=[scena["c"].pk])).content.decode()
    assert "Filtra" in html and chiamate == []


def test_un_filtro_che_non_e_piu_offerto_si_toglie(client, scena):
    a = scena["a"]
    a.spec = {**a.spec, "scelti": {"titolo": {"chiave": "x", "etichetta": "x"}}}        # non è (più) un filtro offerto
    a.save(update_fields=["spec"])
    html = client.get(reverse("ai:conversazione", args=[scena["c"].pk])).content.decode()
    assert "Titolo: x" in html and 'name="campo" value="titolo"' in html                # l'etichetta con la × c'è
    assert client.post(reverse("ai:filtro_artifact", args=[a.pk]), {"campo": "titolo", "chiave": ""}, HTTP_HX_REQUEST="true").status_code == 200
    a.refresh_from_db()
    assert "scelti" not in a.spec


def test_un_filtro_rotto_non_blocca_il_pannello(client, scena, monkeypatch):
    from core import misure
    from core.viste.interroga import ErroreInterrogazione
    originale = misure.valori_filtro

    def valori(spec, campo, request):
        if campo == "tag":
            raise ErroreInterrogazione("campo nascosto")
        return originale(spec, campo, request)
    monkeypatch.setattr(misure, "valori_filtro", valori)
    html = client.get(reverse("ai:filtri_artifact", args=[scena["a"].pk])).content.decode()
    assert "Assegnatario" in html and ">Tag<" not in html


def test_la_pagina_del_grafico_condiviso_dice_il_filtro(client, scena):
    a = scena["a"]
    client.post(reverse("ai:filtro_artifact", args=[a.pk]), {"campo": "assegnatario", "chiave": str(scena["capo"].pk)}, HTTP_HX_REQUEST="true")
    html = client.get(reverse("ai:artifact", args=[a.pk])).content.decode()
    assert "Assegnatario: capo" in html


def test_il_pannello_ha_i_valori_piu_grandi_anche_con_tanti_valori(client, scena):
    persone = [User.objects.create_user(f"u{i:03d}", f"u{i}@example.com", "x") for i in range(105)]
    for p in persone:
        Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo=p.username, stato="aperta", assegnatario=p)
    grande = User.objects.create_user("zeta", "z@example.com", "x")
    for i in range(20):
        Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo=f"z{i}", stato="aperta", assegnatario=grande)
    html = client.get(reverse("ai:filtri_artifact", args=[scena["a"].pk])).content.decode()
    assert f'value="{grande.pk}"' in html
