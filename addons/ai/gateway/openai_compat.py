"""Adattatore per gli endpoint compatibili OpenAI (/chat/completions): OpenAI, OpenRouter, Ollama, vLLM, Gemini.
Il protocollo è stabile: HTTP diretto con httpx2 e Server-Sent Events."""
import json

import httpx2

from .tipi import ChiamataStrumento, ErroreModello, Fine, Testo, Uso

URL_PREDEFINITO = "https://api.openai.com/v1"
MOTIVI = {"stop": "fine", "tool_calls": "strumenti", "length": "limite", "content_filter": "rifiuto"}


def _messaggi(sistema, messaggi):
    risultato = [{"role": "system", "content": sistema}]
    for m in messaggi:
        if m["ruolo"] == "utente":
            risultato.append({"role": "user", "content": m["testo"]})
        elif m["ruolo"] == "assistente":
            testo = "".join(b["testo"] for b in m["blocchi"] if b["tipo"] == "testo")
            chiamate = [{"id": b["id"], "type": "function",
                         "function": {"name": b["nome"], "arguments": json.dumps(b["argomenti"], ensure_ascii=False)}}
                        for b in m["blocchi"] if b["tipo"] == "strumento"]
            risultato.append({"role": "assistant", "content": testo or None, **({"tool_calls": chiamate} if chiamate else {})})
        elif m["ruolo"] == "strumento":
            risultato.extend({"role": "tool", "tool_call_id": r["id"], "content": r["contenuto"]}
                             for r in m["risultati"])
    return risultato


def _errore_http(risposta):
    codice = risposta.status_code
    testo = risposta.text[:500]
    if codice == 429:
        attesa = risposta.headers.get("retry-after")
        return ErroreModello("RATE_LIMIT", testo, float(attesa) if attesa and attesa.isdigit() else None)
    if codice in (401, 403):
        return ErroreModello("AUTENTICAZIONE", "chiave API non valida o senza permessi")
    if codice >= 500:
        return ErroreModello("SERVER", testo)
    if "context" in testo.lower() and "length" in testo.lower():
        return ErroreModello("CONTESTO", testo)
    return ErroreModello("RICHIESTA", testo)


def flusso(modello, chiave, *, sistema, messaggi, strumenti=(), max_token=16000, effort="", http_client=None):
    corpo = {"model": modello.id_api, "messages": _messaggi(sistema, messaggi), "stream": True,
             "stream_options": {"include_usage": True}, "max_tokens": min(max_token, modello.max_output)}
    if strumenti and modello.strumenti:
        corpo["tools"] = [{"type": "function", "function": {"name": s["nome"], "description": s["descrizione"],
                                                             "parameters": s["schema"]}} for s in strumenti]
    if effort and modello.ragionamento:
        corpo["reasoning_effort"] = "high" if effort in ("high", "xhigh", "max") else effort
    intestazioni = {"Content-Type": "application/json"}
    if chiave:
        intestazioni["Authorization"] = f"Bearer {chiave}"
    url = (modello.provider.base_url or URL_PREDEFINITO).rstrip("/") + "/chat/completions"
    http = http_client or httpx2.Client(timeout=httpx2.Timeout(600.0, connect=10.0))
    testo, chiamate, uso, motivo = [], {}, Uso(), "altro"
    try:
        with http.stream("POST", url, json=corpo, headers=intestazioni) as risposta:
            if risposta.status_code >= 400:
                risposta.read()
                raise _errore_http(risposta)
            for riga in risposta.iter_lines():
                if not riga.startswith("data:"):
                    continue
                dati = riga[5:].strip()
                if dati == "[DONE]":
                    break
                pezzo = json.loads(dati)
                if pezzo.get("usage"):
                    u = pezzo["usage"]
                    letti = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                    uso = Uso(input=(u.get("prompt_tokens") or 0) - letti, output=u.get("completion_tokens") or 0,
                              cache_lettura=letti)
                for scelta in pezzo.get("choices") or []:
                    delta = scelta.get("delta") or {}
                    if delta.get("content"):
                        testo.append(delta["content"])
                        yield Testo(delta["content"])
                    for c in delta.get("tool_calls") or []:
                        voce = chiamate.setdefault(c.get("index", 0), {"id": "", "nome": "", "argomenti": ""})
                        voce["id"] = c.get("id") or voce["id"]
                        funzione = c.get("function") or {}
                        voce["nome"] += funzione.get("name") or ""
                        voce["argomenti"] += funzione.get("arguments") or ""
                    if scelta.get("finish_reason"):
                        motivo = MOTIVI.get(scelta["finish_reason"], "altro")
    except httpx2.TimeoutException as e:
        raise ErroreModello("TIMEOUT", str(e)) from e
    except httpx2.TransportError as e:
        raise ErroreModello("RETE", str(e)) from e
    finally:
        if http_client is None:
            http.close()
    blocchi = [{"tipo": "testo", "testo": "".join(testo)}] if testo else []
    for i in sorted(chiamate):
        c = chiamate[i]
        try:
            argomenti = json.loads(c["argomenti"] or "{}")
        except json.JSONDecodeError:
            argomenti = {"_non_valido": c["argomenti"]}
        id_chiamata = c["id"] or f"chiamata_{i}"
        blocchi.append({"tipo": "strumento", "id": id_chiamata, "nome": c["nome"], "argomenti": argomenti})
        yield ChiamataStrumento(id_chiamata, c["nome"], argomenti)
    if not blocchi:
        raise ErroreModello("VUOTA", "il modello non ha risposto")
    yield uso
    yield Fine("strumenti" if chiamate else motivo, blocchi)
