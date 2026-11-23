"""Output strutturato (`formato` di ai.gateway.esegui): lo schema JSON arriva a ogni adattatore nella forma del suo
provider, al posto di un tool_choice obbligato che Opus e Sonnet 5.5 rifiutano."""
import json

import httpx2
import pytest

from ai.gateway import Testo, anthropic_api, esecuzione, esegui, finto, openai_compat
from ai.models import Modello, Provider
from ai.tests.test_gateway import RISPOSTA_ANTHROPIC, _http, _sse

SCHEMA = {"type": "object", "properties": {"voci": {"type": "array", "items": {"type": "string"}}},
          "required": ["voci"], "additionalProperties": False}
FORMATO = {"nome": "voci_capitolato", "schema": SCHEMA}
MESSAGGI = [{"ruolo": "utente", "testo": "Estrai le voci del capitolato."}]


@pytest.fixture
def modelli(db, monkeypatch):
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    anth = Provider.objects.create(nome="Anthropic", tipo="anthropic")
    mistral = Provider.objects.create(nome="Mistral", tipo="mistral", base_url="https://api.mistral.example/v1")
    finto_p = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    return {"sonnet": Modello.objects.create(provider=anth, id_api="claude-sonnet-5-5", etichetta="Sonnet", ragionamento=True),
            "mistral": Modello.objects.create(provider=mistral, id_api="mistral-large-4", etichetta="Large"),
            "finto": Modello.objects.create(provider=finto_p, id_api="finto", etichetta="Finto")}


def test_anthropic_output_config_format_accanto_all_effort(modelli):
    ricevute = []

    def gestore(richiesta):
        ricevute.append(json.loads(richiesta.content))
        return httpx2.Response(200, content=_sse(RISPOSTA_ANTHROPIC), headers={"content-type": "text/event-stream"})

    list(anthropic_api.flusso(modelli["sonnet"], "sk-prova", sistema="s", messaggi=MESSAGGI, effort="low",
                              formato=FORMATO, http_client=_http(gestore)))
    assert ricevute[0]["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert "tool_choice" not in ricevute[0]


def test_anthropic_senza_formato_non_cambia(modelli):
    ricevute = []

    def gestore(richiesta):
        ricevute.append(json.loads(richiesta.content))
        return httpx2.Response(200, content=_sse(RISPOSTA_ANTHROPIC), headers={"content-type": "text/event-stream"})

    list(anthropic_api.flusso(modelli["sonnet"], "sk-prova", sistema="s", messaggi=MESSAGGI, http_client=_http(gestore)))
    assert "output_config" not in ricevute[0]


def test_openai_compat_response_format(modelli):
    ricevute = []
    righe = [{"choices": [{"delta": {"content": '{"voci": ["Scavo"]}'}, "finish_reason": "stop"}]},
             {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}]
    corpo = "".join(f"data: {json.dumps(r)}\n\n" for r in righe) + "data: [DONE]\n\n"

    def gestore(richiesta):
        ricevute.append(json.loads(richiesta.content))
        return httpx2.Response(200, content=corpo.encode(), headers={"content-type": "text/event-stream"})

    pezzi = list(openai_compat.flusso(modelli["mistral"], "k", sistema="s", messaggi=MESSAGGI, formato=FORMATO,
                                      http_client=httpx2.Client(transport=httpx2.MockTransport(gestore))))
    assert ricevute[0]["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "voci_capitolato", "schema": SCHEMA, "strict": True}}
    assert json.loads("".join(p.testo for p in pezzi if isinstance(p, Testo))) == {"voci": ["Scavo"]}


def test_esegui_passa_il_formato_all_adattatore(modelli):
    with finto.con_copione([['{"voci": ["Scavo", "Getto"]}']]) as chiamate:
        pezzi = list(esegui([(modelli["finto"], "")], sistema="s", messaggi=MESSAGGI, formato=FORMATO))
    assert chiamate[0]["formato"] == FORMATO
    assert json.loads("".join(p.testo for p in pezzi if isinstance(p, Testo))) == {"voci": ["Scavo", "Getto"]}
