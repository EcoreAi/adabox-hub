"""Provider Mistral e catalogo letto dal provider: solo modelli di chat, alias raccolti, dismessi fuori, prezzi di
OpenRouter, importazione che non tocca i prezzi scritti, chat instradata all'API di Mistral."""
import json
from decimal import Decimal

import httpx2
import pytest
from django.urls import reverse

from ai import catalogo, catalogo_remoto
from ai.gateway import openai_compat
from ai.models import AnelloCatena, Modello, Profilo, Provider
from core import cifratura

MISTRAL = {"object": "list", "data": [
    {"id": "mistral-large-2511", "name": "Mistral Large", "description": "Il modello più capace", "max_context_length": 262144,
     "aliases": ["mistral-large-latest"], "capabilities": {"completion_chat": True, "function_calling": True, "vision": True}},
    {"id": "mistral-large-latest", "name": "Mistral Large", "max_context_length": 262144, "aliases": ["mistral-large-2511"],
     "capabilities": {"completion_chat": True, "function_calling": True, "vision": True}},
    {"id": "mistral-small-2603", "name": "Mistral Small", "max_context_length": 131072, "aliases": [],
     "capabilities": {"completion_chat": True, "function_calling": True, "vision": False}},
    {"id": "mistral-embed", "name": "Mistral Embed", "capabilities": {"completion_chat": False}},
    {"id": "open-mistral-7b", "deprecation": "2025-03-30T00:00:00Z", "capabilities": {"completion_chat": True}},
]}


@pytest.fixture
def mistral(db, monkeypatch):
    richieste = []

    def risposta(r):
        richieste.append(r)
        return httpx2.Response(200, json=MISTRAL) if r.url.path == "/v1/models" else httpx2.Response(404)
    monkeypatch.setattr(catalogo_remoto, "HTTP", httpx2.Client(transport=httpx2.MockTransport(risposta)))
    provider = Provider.objects.create(nome="Mistral", tipo=Provider.MISTRAL, chiave_cifrata=cifratura.cifra("chiave-mistral"))
    return provider, richieste


def test_lettura_del_catalogo_mistral(mistral):
    provider, richieste = mistral
    voci = catalogo_remoto.leggi(provider)
    assert str(richieste[0].url) == "https://api.mistral.ai/v1/models"
    assert richieste[0].headers["authorization"] == "Bearer chiave-mistral"
    assert [v.id_api for v in voci] == ["mistral-large-2511", "mistral-small-2603"]       # alias, embed e dismessi fuori
    large = voci[0]
    assert large.contesto == 262144 and large.visione and large.strumenti and large.alias == ("mistral-large-latest",)


def test_importazione_senza_toccare_i_prezzi(mistral):
    provider, _ = mistral
    voci = catalogo_remoto.leggi(provider)
    assert catalogo_remoto.importa(provider, voci, {"mistral-large-2511"}) == (1, 0)
    m = Modello.objects.get(id_api="mistral-large-2511")
    assert m.etichetta == "Mistral Large" and m.contesto == 262144 and m.visione and m.residenza_ue and m.prezzo_input is None
    m.prezzo_input = Decimal("2")
    m.save()
    voci = catalogo_remoto.leggi(provider)
    assert voci[-1].presente                                                            # in fondo, già in uso
    assert catalogo_remoto.importa(provider, voci, {"mistral-large-2511", "mistral-small-2603"}) == (1, 1)
    assert Modello.objects.get(id_api="mistral-large-2511").prezzo_input == Decimal("2")


def test_senza_chiave_e_errori(db, monkeypatch):
    provider = Provider.objects.create(nome="Mistral", tipo=Provider.MISTRAL)
    with pytest.raises(catalogo_remoto.CatalogoNonDisponibile, match="chiave"):
        catalogo_remoto.leggi(provider)
    provider.chiave_cifrata = cifratura.cifra("sbagliata")
    provider.save()
    monkeypatch.setattr(catalogo_remoto, "HTTP", httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(401))))
    with pytest.raises(catalogo_remoto.CatalogoNonDisponibile, match="non valida"):
        catalogo_remoto.leggi(provider)
    anthropic = Provider.objects.create(nome="Anthropic", tipo=Provider.ANTHROPIC)
    with pytest.raises(catalogo_remoto.CatalogoNonDisponibile):
        catalogo_remoto.leggi(anthropic)


def test_prezzi_da_openrouter(db, monkeypatch):
    dati = {"data": [{"id": "z-ai/glm-5", "name": "GLM 5", "context_length": 200000,
                      "pricing": {"prompt": "0.0000006", "completion": "0.0000022"}}]}
    monkeypatch.setattr(catalogo_remoto, "HTTP", httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=dati))))
    provider = Provider.objects.create(nome="OpenRouter", tipo=Provider.OPENAI_COMPAT, base_url="https://openrouter.ai/api/v1")
    voce = catalogo_remoto.leggi(provider)[0]
    assert voce.prezzo_input == Decimal("0.6000") and voce.prezzo_output == Decimal("2.2000") and voce.contesto == 200000


def test_chat_verso_mistral_e_catena(db):
    provider = Provider.objects.create(nome="Mistral", tipo=Provider.MISTRAL)
    modello = Modello.objects.create(provider=provider, id_api="mistral-small-2603", etichetta="Mistral Small")
    profilo = Profilo.objects.create(nome="Chat", compito="chat")
    AnelloCatena.objects.create(profilo=profilo, modello=modello)
    with pytest.raises(catalogo.NessunModello):
        catalogo.catena(profilo)                                                          # senza chiave si salta
    provider.chiave_cifrata = cifratura.cifra("k")
    provider.save()
    assert catalogo.catena(profilo)[0][0] == modello
    inviate = []

    def risposta(r):
        inviate.append(r)
        corpo = ('data: {"choices":[{"delta":{"content":"Ciao"},"finish_reason":"stop"}]}\n\n'
                 'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":1}}\n\ndata: [DONE]\n\n')
        return httpx2.Response(200, text=corpo, headers={"content-type": "text/event-stream"})
    pezzi = list(openai_compat.flusso(modello, "k", sistema="s", messaggi=[{"ruolo": "utente", "testo": "ciao"}],
                                      http_client=httpx2.Client(transport=httpx2.MockTransport(risposta))))
    assert str(inviate[0].url) == "https://api.mistral.ai/v1/chat/completions"
    assert json.loads(inviate[0].content)["model"] == "mistral-small-2603" and pezzi[-1].motivo == "fine"


def test_pagina_del_catalogo(client, superuser, mistral):
    provider, _ = mistral
    assert "Scegli dal catalogo" in client.get(reverse("ai:provider_dettaglio", args=[provider.pk])).content.decode()
    pagina = client.get(reverse("ai:catalogo_provider", args=[provider.pk])).content.decode()
    assert "Mistral Large" in pagina and "mistral-large-latest" in pagina and "Mistral Embed" not in pagina
    client.post(reverse("ai:catalogo_provider", args=[provider.pk]), {"scelti": ["mistral-small-2603"]})
    assert list(Modello.objects.values_list("id_api", flat=True)) == ["mistral-small-2603"]


def test_scheda_del_provider_con_modelli_e_prezzi(client, superuser, db):
    provider = Provider.objects.create(nome="Anthropic", tipo=Provider.ANTHROPIC, chiave_cifrata=cifratura.cifra("sk-ant-abcdefgh1234"))
    con = Modello.objects.create(provider=provider, id_api="claude-haiku-5-5", etichetta="Claude Haiku 5.5",
                                 prezzo_input=Decimal("0.1"), prezzo_output=Decimal("0.5"))
    senza = Modello.objects.create(provider=provider, id_api="claude-x", etichetta="Claude X")
    pagina = client.get(reverse("ai:provider_dettaglio", args=[provider.pk])).content.decode()
    assert "Modelli di Anthropic (2)" in pagina and "Claude Haiku 5.5" in pagina and "manca" in pagina
    assert reverse("ai:modelli_modifica", args=[senza.pk]) in pagina and "1234" in pagina and "sk-ant-abcdefgh1234" not in pagina
    assert "Nuova chiave" not in pagina and "Scegli dal catalogo" not in pagina                   # Anthropic: niente catalogo
    assert reverse("ai:modelli_modifica", args=[con.pk]) in pagina


def test_livelli_con_un_modello_senza_prezzo(db):
    from ai.pagine import livelli_modello
    provider = Provider.objects.create(nome="Mistral", tipo=Provider.MISTRAL, chiave_cifrata=cifratura.cifra("k"))
    caro = Modello.objects.create(provider=provider, id_api="large", etichetta="Large", sceglibile=True,
                                  prezzo_input=Decimal("2"), prezzo_output=Decimal("6"))
    gratis = Modello.objects.create(provider=provider, id_api="small", etichetta="Small", sceglibile=True)
    assert livelli_modello(None) == [("standard", gratis), ("max", caro)]


def test_livelli_assegnati_a_mano(db):
    from ai.pagine import livelli_modello
    provider = Provider.objects.create(nome="Mistral", tipo=Provider.MISTRAL, chiave_cifrata=cifratura.cifra("k"))
    large = Modello.objects.create(provider=provider, id_api="large", etichetta="Large", prezzo_output=Decimal("6"))
    medium = Modello.objects.create(provider=provider, id_api="medium", etichetta="Medium", prezzo_output=Decimal("2"),
                                    livello_chat=Modello.AVANZATO)
    assert medium.sceglibile and livelli_modello(None) == [("max", medium)]          # Avanzato anche se non è il più caro
    large.livello_chat = Modello.AVANZATO
    large.save()
    medium.refresh_from_db()
    assert medium.livello_chat == "" and livelli_modello(None)[0] == ("max", large)  # uno solo per livello
    medium.livello_chat = Modello.VELOCE
    medium.save()
    assert livelli_modello(None) == [("standard", medium), ("max", large)]


def test_risposta_a_pezzi_dei_modelli_che_ragionano(db):
    """DeepSeek e Magistral su Mistral mandano il contenuto come lista: si tiene il testo, il ragionamento no."""
    provider = Provider.objects.create(nome="Mistral", tipo=Provider.MISTRAL)
    modello = Modello.objects.create(provider=provider, id_api="deepseek-v4-1-flash", etichetta="DeepSeek", ragionamento=True)
    pensiero = {"type": "thinking", "thinking": [{"type": "text", "text": "devo salutare"}]}
    righe = [{"choices": [{"delta": {"content": [pensiero]}}]},
             {"choices": [{"delta": {"content": [{"type": "text", "text": "Buon"}]}}]},
             {"choices": [{"delta": {"content": "giorno"}, "finish_reason": "stop"}]},
             {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}]
    corpo = "".join(f"data: {json.dumps(r)}\n\n" for r in righe) + "data: [DONE]\n\n"
    trasporto = httpx2.MockTransport(lambda r: httpx2.Response(200, text=corpo, headers={"content-type": "text/event-stream"}))
    pezzi = list(openai_compat.flusso(modello, "k", sistema="s", messaggi=[{"ruolo": "utente", "testo": "ciao"}],
                                      http_client=httpx2.Client(transport=trasporto)))
    testi = [p.testo for p in pezzi if hasattr(p, "testo")]
    assert testi == ["Buon", "giorno"] and pezzi[-1].blocchi[0]["testo"] == "Buongiorno"


def test_livello_di_ragionamento_rifiutato_si_riprova_senza(db):
    provider = Provider.objects.create(nome="Compatibile", tipo=Provider.OPENAI_COMPAT, base_url="https://esempio.it/v1")
    modello = Modello.objects.create(provider=provider, id_api="x", etichetta="X", ragionamento=True)
    corpi = []

    def risposta(r):
        corpi.append(json.loads(r.content))
        if "reasoning_effort" in corpi[-1]:
            return httpx2.Response(400, json={"message": "reasoning_effort 'low' is not supported for this model"})
        testo = 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        return httpx2.Response(200, text=testo, headers={"content-type": "text/event-stream"})
    pezzi = list(openai_compat.flusso(modello, "k", sistema="s", messaggi=[{"ruolo": "utente", "testo": "ciao"}], effort="low",
                                      http_client=httpx2.Client(transport=httpx2.MockTransport(risposta))))
    assert len(corpi) == 2 and "reasoning_effort" not in corpi[1] and pezzi[-1].blocchi[0]["testo"] == "ok"


def test_livelli_di_ragionamento_per_mistral(db):
    provider = Provider.objects.create(nome="Mistral", tipo=Provider.MISTRAL)
    modello = Modello.objects.create(provider=provider, id_api="deepseek", etichetta="D", ragionamento=True)
    inviati = []

    def risposta(r):
        inviati.append(json.loads(r.content).get("reasoning_effort"))
        testo = 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        return httpx2.Response(200, text=testo, headers={"content-type": "text/event-stream"})
    for effort in ("low", "medium", "high", "xhigh", "max"):
        list(openai_compat.flusso(modello, "k", sistema="s", messaggi=[{"ruolo": "utente", "testo": "c"}], effort=effort,
                                  http_client=httpx2.Client(transport=httpx2.MockTransport(risposta))))
    assert inviati == ["low", "high", "high", "xhigh", "max"]
