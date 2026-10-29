from decimal import Decimal

import pytest

from ai import catalogo
from ai.models import AnelloCatena, ChiaveAzienda, Modello, Profilo, Provider
from core import cifratura
from core.models import Azienda


@pytest.fixture
def iniziali(db):
    catalogo.crea_iniziali()
    return Provider.objects.get(nome="Anthropic")


def test_dati_iniziali_e_idempotenza(iniziali):
    assert set(Modello.objects.filter(provider=iniziali).values_list("id_api", flat=True)) == {
        "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}
    haiku = Modello.objects.get(id_api="claude-haiku-5-5")
    assert (haiku.prezzo_input, haiku.prezzo_output, haiku.contesto) == (Decimal("0.1000"), Decimal("0.5000"), 1_000_000)
    chat = Profilo.objects.get(compito="chat")
    assert [a.modello.id_api for a in chat.catena.all()] == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert catalogo.crea_iniziali() is False and Provider.objects.count() == 2


def test_costo(iniziali):
    haiku = Modello.objects.get(id_api="claude-haiku-5-5")
    costo = haiku.costo({"input": 1_000_000, "output": 200_000, "cache_lettura": 500_000, "cache_scrittura": 0})
    assert costo == Decimal("0.1") + Decimal("0.1") + Decimal("0.005")


def test_profilo_piu_specifico(iniziali):
    azienda = Azienda.objects.get(pk=1)
    generale = Profilo.objects.get(compito="chat")
    per_app = Profilo.objects.create(nome="Vendite", compito="chat", app="vendite")
    per_azienda = Profilo.objects.create(nome="Azienda", compito="chat", azienda=azienda)
    entrambi = Profilo.objects.create(nome="Azienda+vendite", compito="chat", app="vendite", azienda=azienda)
    assert catalogo.profilo_per("chat") == generale
    assert catalogo.profilo_per("chat", app="vendite") == per_app
    assert catalogo.profilo_per("chat", azienda=azienda) == per_azienda
    assert catalogo.profilo_per("chat", azienda=azienda, app="vendite") == entrambi
    assert catalogo.profilo_per("chat", app="crm") == generale
    Profilo.objects.filter(compito="titoli").delete()
    assert catalogo.profilo_per("titoli") == generale                       # ripiega sulla chat


def test_catena_e_chiavi(iniziali):
    azienda = Azienda.objects.get(pk=1)
    chat = Profilo.objects.get(compito="chat")
    with pytest.raises(catalogo.NessunModello, match="chiave"):
        catalogo.catena(chat)
    iniziali.chiave_cifrata = cifratura.cifra("sk-globale")
    iniziali.save()
    assert [(m.id_api, k) for m, k in catalogo.catena(chat)] == [("claude-haiku-5-5", "sk-globale"),
                                                                 ("claude-sonnet-5-5", "sk-globale")]
    ChiaveAzienda.objects.create(provider=iniziali, azienda=azienda, chiave_cifrata=cifratura.cifra("sk-azienda"))
    assert catalogo.catena(chat, azienda)[0][1] == "sk-azienda"
    Modello.objects.filter(id_api="claude-haiku-5-5").update(attivo=False)
    assert [m.id_api for m, _ in catalogo.catena(chat)] == ["claude-sonnet-5-5"]


def test_viste_chiave_cifrata(client, superuser, iniziali):
    r = client.post(f"/ai/provider/{iniziali.pk}/modifica/", {"nome": "Anthropic", "tipo": "anthropic",
                                                              "nuova_chiave": "sk-ant-segretissima-9876", "attivo": "on"})
    iniziali.refresh_from_db()
    assert r.status_code == 302 and "sk-ant" not in iniziali.chiave_cifrata
    assert iniziali.chiave_per() == "sk-ant-segretissima-9876"
    html = client.get("/ai/provider/").content.decode()
    assert "••••9876" in html and "segretissima" not in html
    form = client.get(f"/ai/provider/{iniziali.pk}/modifica/").content.decode()
    assert "segretissima" not in form and "attuale: ••••9876" in form
    client.post(f"/ai/provider/{iniziali.pk}/modifica/", {"nome": "Anthropic", "tipo": "anthropic", "attivo": "on"})
    iniziali.refresh_from_db()
    assert iniziali.chiave_per() == "sk-ant-segretissima-9876"            # vuoto = invariata
    r = client.post("/ai/chiavi/nuovo/", {"provider": iniziali.pk, "azienda": 1, "chiave": "sk-az-1111"})
    assert r.status_code == 302 and iniziali.chiave_per(Azienda.objects.get(pk=1)) == "sk-az-1111"


def test_profilo_con_catena_dal_form(client, superuser, iniziali):
    sonnet = Modello.objects.get(id_api="claude-sonnet-5-5")
    dati = {"nome": "Analisi", "compito": "riassunti", "effort": "medium", "max_token": "4000", "attivo": "on",
            "righe0-TOTAL_FORMS": "1", "righe0-INITIAL_FORMS": "0", "righe0-MIN_NUM_FORMS": "0",
            "righe0-MAX_NUM_FORMS": "1000", "righe0-0-modello": sonnet.pk, "righe0-0-ordine": "1"}
    assert client.post("/ai/profili/nuovo/", dati).status_code == 302
    p = Profilo.objects.get(nome="Analisi")
    assert list(AnelloCatena.objects.filter(profilo=p).values_list("modello__id_api", flat=True)) == ["claude-sonnet-5-5"]
    assert "Claude Sonnet 5.5" in client.get("/ai/profili/").content.decode()
