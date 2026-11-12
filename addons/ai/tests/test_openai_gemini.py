"""OpenAI e Gemini come provider di prima classe: ciò che li distingue dagli altri endpoint compatibili."""
import json

import httpx2
import pytest

from ai import catalogo_remoto
from ai.gateway import ChiamataStrumento, anthropic_api, esecuzione, openai_compat
from ai.models import Modello, Provider

STRUMENTI = [{"nome": "data_e_ora", "descrizione": "Data e ora correnti", "schema": {
    "type": "object", "properties": {"fuso": {"type": "string"}}, "required": []}}]
FIRMA = {"google": {"thought_signature": "firma-opaca-del-ragionamento=="}}


def _risposta(righe, ricevute):
    corpo = "".join(f"data: {json.dumps(r)}\n\n" for r in righe) + "data: [DONE]\n\n"

    def gestore(richiesta):
        ricevute.append((str(richiesta.url), richiesta.headers.get("authorization"), json.loads(richiesta.content)))
        return httpx2.Response(200, content=corpo.encode(), headers={"content-type": "text/event-stream"})
    return httpx2.Client(transport=httpx2.MockTransport(gestore))


@pytest.fixture
def modelli(db):
    openai = Provider.objects.create(nome="OpenAI", tipo="openai")
    gemini = Provider.objects.create(nome="Gemini", tipo="gemini")
    return {"gpt": Modello.objects.create(provider=openai, id_api="gpt-6-astra", etichetta="GPT", ragionamento=True, max_output=4000),
            "gemini": Modello.objects.create(provider=gemini, id_api="gemini-3.7-flash", etichetta="Gemini", ragionamento=True)}


def test_openai_indirizzo_tetto_e_livelli(modelli):
    """I modelli di OpenAI che ragionano rifiutano max_tokens: si manda max_completion_tokens, e il livello così com'è."""
    ricevute = []
    righe = [{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]},
             {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}]
    for effort in ("low", "xhigh", "max"):
        pezzi = list(openai_compat.flusso(modelli["gpt"], "sk-proj-x", sistema="s", messaggi=[{"ruolo": "utente", "testo": "ciao"}],
                                          max_token=16000, effort=effort, http_client=_risposta(righe, ricevute)))
    url, autorizzazione, corpo = ricevute[0]
    assert url == "https://api.openai.com/v1/chat/completions" and autorizzazione == "Bearer sk-proj-x"
    assert corpo["max_completion_tokens"] == 4000 and "max_tokens" not in corpo
    assert [c["reasoning_effort"] for _, _, c in ricevute] == ["low", "xhigh", "max"]
    assert pezzi[-1].blocchi == [{"tipo": "testo", "testo": "ok"}]
    assert esecuzione.ADATTATORI["openai"] is openai_compat.flusso and esecuzione.ADATTATORI["gemini"] is openai_compat.flusso


def test_gemini_la_firma_del_ragionamento_torna_indietro(modelli):
    """Dalla serie 3 Gemini mette una firma su ogni chiamata a uno strumento e la rivuole identica: senza, risponde 400."""
    ricevute = []
    righe = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "extra_content": FIRMA,
                                                     "function": {"name": "data_e_ora", "arguments": "{}"}}]}}]},
             {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "call_2", "function": {"name": "data_e_ora", "arguments": "{}"}}]},
                           "finish_reason": "tool_calls"}]},
             {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}]
    pezzi = list(openai_compat.flusso(modelli["gemini"], "AIza-x", sistema="s", messaggi=[{"ruolo": "utente", "testo": "che ore sono?"}],
                                      strumenti=STRUMENTI, effort="xhigh", http_client=_risposta(righe, ricevute)))
    url, _, corpo = ricevute[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert "max_tokens" in corpo and corpo["reasoning_effort"] == "high"
    blocchi = pezzi[-1].blocchi
    assert blocchi[0]["extra"] == FIRMA and "extra" not in blocchi[1]                       # in parallelo firma solo la prima
    assert [p.id for p in pezzi if isinstance(p, ChiamataStrumento)] == ["call_1", "call_2"]

    storia = [{"ruolo": "utente", "testo": "che ore sono?"}, {"ruolo": "assistente", "blocchi": blocchi},
              {"ruolo": "strumento", "risultati": [{"id": "call_1", "contenuto": "10:00"}, {"id": "call_2", "contenuto": "10:00"}]}]
    list(openai_compat.flusso(modelli["gemini"], "AIza-x", sistema="s", messaggi=storia, strumenti=STRUMENTI,
                              http_client=_risposta([{"choices": [{"delta": {"content": "Le 10."}, "finish_reason": "stop"}]}], ricevute)))
    rimandate = ricevute[1][2]["messages"][2]["tool_calls"]
    assert rimandate[0]["extra_content"] == FIRMA and "extra_content" not in rimandate[1]


def test_la_firma_di_gemini_non_va_agli_altri_fornitori(modelli):
    """Se la catena passa a un altro provider, la storia resta valida: la firma è un fatto privato di Gemini."""
    blocchi = [{"tipo": "strumento", "id": "call_1", "nome": "data_e_ora", "argomenti": {}, "extra": FIRMA}]
    storia = [{"ruolo": "utente", "testo": "che ore sono?"}, {"ruolo": "assistente", "blocchi": blocchi},
              {"ruolo": "strumento", "risultati": [{"id": "call_1", "contenuto": "10:00"}]}]
    ricevute = []
    list(openai_compat.flusso(modelli["gpt"], "k", sistema="s", messaggi=storia,
                              http_client=_risposta([{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}], ricevute)))
    assert "extra_content" not in ricevute[0][2]["messages"][2]["tool_calls"][0]
    assert anthropic_api._messaggi(storia)[1]["content"] == [{"type": "tool_use", "id": "call_1", "name": "data_e_ora", "input": {}}]
    # Gemini configurato alla vecchia maniera, come «compatibile OpenAI» con il suo indirizzo: vale lo stesso
    vecchio = Provider.objects.create(nome="Gemini compat", tipo="openai_compat", base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
    modello = Modello.objects.create(provider=vecchio, id_api="gemini-3.7-flash", etichetta="G")
    list(openai_compat.flusso(modello, "k", sistema="s", messaggi=storia,
                              http_client=_risposta([{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}], ricevute)))
    assert ricevute[1][2]["messages"][2]["tool_calls"][0]["extra_content"] == FIRMA


def test_catalogo_di_openai_e_gemini(modelli, monkeypatch):
    from core import cifratura
    elenchi = {"api.openai.com": {"data": [{"id": "gpt-6-astra"}, {"id": "gpt-6-luna"}, {"id": "text-embedding-4-large"},
                                           {"id": "gpt-6-realtime"}, {"id": "whisper-2"}, {"id": "gpt-image-2"}]},
               "generativelanguage.googleapis.com": {"data": [{"id": "models/gemini-3.7-flash"}, {"id": "models/gemini-4-argon"},
                                                              {"id": "models/gemini-embedding-002"}, {"id": "models/imagen-5"}]}}
    chiamate = []

    def risposta(r):
        chiamate.append((str(r.url), r.headers.get("authorization")))
        return httpx2.Response(200, json=elenchi[r.url.host])
    monkeypatch.setattr(catalogo_remoto, "HTTP", httpx2.Client(transport=httpx2.MockTransport(risposta)))
    with pytest.raises(catalogo_remoto.CatalogoNonDisponibile, match="chiave API"):
        catalogo_remoto.leggi(modelli["gpt"].provider)
    for nome in ("gpt", "gemini"):
        Provider.objects.filter(pk=modelli[nome].provider_id).update(chiave_cifrata=cifratura.cifra("chiave-" + nome))
    openai = catalogo_remoto.leggi(Provider.objects.get(tipo="openai"))
    assert {v.id_api: v.presente for v in openai} == {"gpt-6-astra": True, "gpt-6-luna": False}
    gemini = catalogo_remoto.leggi(Provider.objects.get(tipo="gemini"))
    assert {v.id_api: v.presente for v in gemini} == {"gemini-3.7-flash": True, "gemini-4-argon": False}
    assert chiamate == [("https://api.openai.com/v1/models", "Bearer chiave-gpt"),
                        ("https://generativelanguage.googleapis.com/v1beta/openai/models", "Bearer chiave-gemini")]
