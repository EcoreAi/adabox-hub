import json

import anthropic
import httpx2
import pytest

from ai import catalogo
from ai.gateway import ChiamataStrumento, ErroreModello, Fine, Inizio, Testo, Uso, esecuzione, esegui, finto
from ai.gateway import anthropic_api, openai_compat
from ai.models import Modello, Provider

STRUMENTI = [{"nome": "data_e_ora", "descrizione": "Data e ora correnti", "schema": {
    "type": "object", "properties": {"fuso": {"type": "string"}}, "required": []}}]
MESSAGGI = [{"ruolo": "utente", "testo": "Che ore sono?"}]


@pytest.fixture
def modelli(db, monkeypatch):
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    catalogo.crea_iniziali()
    finto_p = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    oa = Provider.objects.create(nome="OpenRouter", tipo="openai_compat", base_url="https://openrouter.example/v1")
    return {"haiku": Modello.objects.get(id_api="claude-haiku-5-5"),
            "sonnet": Modello.objects.get(id_api="claude-sonnet-5-5"),
            "finto": Modello.objects.create(provider=finto_p, id_api="finto", etichetta="Finto"),
            "oa": Modello.objects.create(provider=oa, id_api="openai/gpt-x", etichetta="GPT X")}


def _sse(eventi):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in eventi).encode()


RISPOSTA_ANTHROPIC = [
    {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant",
                                          "model": "claude-haiku-5-5", "content": [], "stop_reason": None,
                                          "stop_sequence": None,
                                          "usage": {"input_tokens": 12, "output_tokens": 1,
                                                    "cache_creation_input_tokens": 300,
                                                    "cache_read_input_tokens": 2000}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Controllo "}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "subito."}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1,
     "content_block": {"type": "tool_use", "id": "toolu_1", "name": "data_e_ora", "input": {}}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "input_json_delta", "partial_json": "{\"fuso\": \"Europe/Rome\"}"}},
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 25}},
    {"type": "message_stop"},
]


def _http(gestore):
    return anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(gestore))


def test_anthropic_stream_strumenti_cache_effort(modelli):
    ricevute = []

    def gestore(richiesta):
        ricevute.append(json.loads(richiesta.content))
        return httpx2.Response(200, content=_sse(RISPOSTA_ANTHROPIC), headers={"content-type": "text/event-stream"})

    pezzi = list(anthropic_api.flusso(modelli["haiku"], "sk-prova", sistema="Sei l'assistente.", messaggi=MESSAGGI,
                                      strumenti=STRUMENTI, max_token=500000, effort="low",
                                      http_client=_http(gestore)))
    corpo = ricevute[0]
    assert corpo["model"] == "claude-haiku-5-5" and corpo["max_tokens"] == 128000
    assert corpo["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert corpo["tools"][-1]["cache_control"] == {"type": "ephemeral"} and corpo["output_config"] == {"effort": "low"}
    assert [p.testo for p in pezzi if isinstance(p, Testo)] == ["Controllo ", "subito."]
    chiamata = next(p for p in pezzi if isinstance(p, ChiamataStrumento))
    assert (chiamata.id, chiamata.nome, chiamata.argomenti) == ("toolu_1", "data_e_ora", {"fuso": "Europe/Rome"})
    uso = next(p for p in pezzi if isinstance(p, Uso))
    assert (uso.input, uso.output, uso.cache_scrittura, uso.cache_lettura) == (12, 25, 300, 2000)
    fine = pezzi[-1]
    assert isinstance(fine, Fine) and fine.motivo == "strumenti" and fine.nativo["provider"] == "anthropic"
    assert fine.nativo["contenuto"][1]["type"] == "tool_use"


def test_anthropic_rimanda_il_contenuto_nativo(modelli):
    ricevute = []

    def gestore(richiesta):
        ricevute.append(json.loads(richiesta.content))
        return httpx2.Response(200, content=_sse(RISPOSTA_ANTHROPIC), headers={"content-type": "text/event-stream"})

    nativo = [{"type": "thinking", "thinking": "", "signature": "firma-segreta"}, {"type": "text", "text": "Ciao"}]
    storia = [*MESSAGGI, {"ruolo": "assistente", "blocchi": [{"tipo": "testo", "testo": "Ciao"}],
                          "nativo": {"provider": "anthropic", "contenuto": nativo}},
              {"ruolo": "strumento", "risultati": [{"id": "toolu_0", "contenuto": "ok", "errore": True}]}]
    list(anthropic_api.flusso(modelli["haiku"], "k", sistema="s", messaggi=storia, http_client=_http(gestore)))
    messaggi = ricevute[0]["messages"]
    assert messaggi[1] == {"role": "assistant", "content": nativo}                 # invariato, firma compresa
    assert messaggi[2]["content"][0] == {"type": "tool_result", "tool_use_id": "toolu_0", "content": "ok",
                                         "is_error": True}


@pytest.mark.parametrize("stato,codice", [(429, "RATE_LIMIT"), (401, "AUTENTICAZIONE"), (500, "SERVER"),
                                          (400, "RICHIESTA")])
def test_anthropic_errori_normalizzati(modelli, stato, codice):
    def gestore(richiesta):
        return httpx2.Response(stato, json={"type": "error", "error": {"type": "x", "message": "no"}},
                               headers={"retry-after": "3"})
    with pytest.raises(ErroreModello) as e:
        list(anthropic_api.flusso(modelli["haiku"], "k", sistema="s", messaggi=MESSAGGI, http_client=_http(gestore)))
    assert e.value.codice == codice
    if codice == "RATE_LIMIT":
        assert e.value.attesa == 3.0 and e.value.riprovabile


def test_openai_compat_stream(modelli):
    righe = [
        {"choices": [{"delta": {"content": "Ecco "}}]},
        {"choices": [{"delta": {"content": "fatto."}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "data_e_ora",
                                                                                         "arguments": "{\"fu"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "so\": \"UTC\"}"}}]},
                      "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                  "prompt_tokens_details": {"cached_tokens": 60}}},
    ]
    corpo = "".join(f"data: {json.dumps(r)}\n\n" for r in righe) + "data: [DONE]\n\n"
    ricevute = []

    def gestore(richiesta):
        ricevute.append((str(richiesta.url), richiesta.headers.get("authorization"), json.loads(richiesta.content)))
        return httpx2.Response(200, content=corpo.encode(), headers={"content-type": "text/event-stream"})

    storia = [*MESSAGGI, {"ruolo": "assistente", "blocchi": [{"tipo": "strumento", "id": "c0", "nome": "x",
                                                              "argomenti": {}}]},
              {"ruolo": "strumento", "risultati": [{"id": "c0", "contenuto": "r"}]}]
    pezzi = list(openai_compat.flusso(modelli["oa"], "sk-or", sistema="Sei l'assistente.", messaggi=storia,
                                      strumenti=STRUMENTI, http_client=httpx2.Client(transport=httpx2.MockTransport(gestore))))
    url, autorizzazione, corpo_inviato = ricevute[0]
    assert url == "https://openrouter.example/v1/chat/completions" and autorizzazione == "Bearer sk-or"
    assert corpo_inviato["messages"][0] == {"role": "system", "content": "Sei l'assistente."}
    assert corpo_inviato["messages"][2]["tool_calls"][0]["id"] == "c0"
    assert corpo_inviato["messages"][3] == {"role": "tool", "tool_call_id": "c0", "content": "r"}
    assert corpo_inviato["tools"][0]["function"]["name"] == "data_e_ora"
    assert "".join(p.testo for p in pezzi if isinstance(p, Testo)) == "Ecco fatto."
    chiamata = next(p for p in pezzi if isinstance(p, ChiamataStrumento))
    assert chiamata.argomenti == {"fuso": "UTC"} and chiamata.id == "call_1"
    uso = next(p for p in pezzi if isinstance(p, Uso))
    assert (uso.input, uso.cache_lettura, uso.output) == (40, 60, 20)
    assert pezzi[-1].motivo == "strumenti"


def test_openai_compat_errore(modelli):
    http = httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(503, text="giù")))
    with pytest.raises(ErroreModello, match="SERVER"):
        list(openai_compat.flusso(modelli["oa"], "", sistema="s", messaggi=MESSAGGI, http_client=http))


def test_retry_e_fallback_prima_della_risposta(modelli, monkeypatch):
    tentativi = []

    def instabile(modello, chiave, **kw):
        tentativi.append(modello.id_api)
        raise ErroreModello("RATE_LIMIT", "troppe richieste")
        yield                                                        # pragma: no cover

    monkeypatch.setitem(esecuzione.ADATTATORI, "anthropic", instabile)
    with finto.con_copione([["Risposta dal finto"]]):
        pezzi = list(esegui([(modelli["haiku"], "k"), (modelli["finto"], "")], sistema="s", messaggi=MESSAGGI))
    assert tentativi == ["claude-haiku-5-5"] * esecuzione.TENTATIVI
    assert isinstance(pezzi[0], Inizio) and pezzi[0].modello == modelli["finto"]
    assert pezzi[1].testo == "Risposta dal finto"


def test_errore_non_riprovabile_passa_subito_al_successivo(modelli, monkeypatch):
    tentativi = []

    def senza_chiave(modello, chiave, **kw):
        tentativi.append(1)
        raise ErroreModello("AUTENTICAZIONE")
        yield                                                        # pragma: no cover

    monkeypatch.setitem(esecuzione.ADATTATORI, "anthropic", senza_chiave)
    with finto.con_copione([["ok"]]):
        list(esegui([(modelli["haiku"], "k"), (modelli["finto"], "")], sistema="s", messaggi=MESSAGGI))
    assert tentativi == [1]


def test_niente_fallback_dopo_il_primo_pezzo(modelli, monkeypatch):
    def a_meta(modello, chiave, **kw):
        yield Testo("Inizio della risposta…")
        raise ErroreModello("RETE", "caduta")

    monkeypatch.setitem(esecuzione.ADATTATORI, "anthropic", a_meta)
    ricevuti = []
    with pytest.raises(ErroreModello, match="RETE"):
        for p in esegui([(modelli["haiku"], "k"), (modelli["finto"], "")], sistema="s", messaggi=MESSAGGI):
            ricevuti.append(p)
    assert [type(p).__name__ for p in ricevuti] == ["Inizio", "Testo"]


def test_tutti_falliscono(modelli):
    with finto.con_copione([[("errore", "SERVER")]] * 3):
        with pytest.raises(ErroreModello, match="SERVER"):
            list(esegui([(modelli["finto"], "")], sistema="s", messaggi=MESSAGGI))
