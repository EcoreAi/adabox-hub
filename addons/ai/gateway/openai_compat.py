"""Adattatore per gli endpoint compatibili OpenAI (/chat/completions): OpenAI, Gemini, Mistral, OpenRouter, Ollama, vLLM.
Il protocollo è stabile: HTTP diretto con httpx2 e Server-Sent Events. Le differenze tra i fornitori stanno qui:

- OpenAI vuole `max_completion_tokens` (i suoi modelli che ragionano rifiutano `max_tokens`) e accetta tutti i livelli
  di ragionamento;
- Gemini, dalla serie 3, mette su ogni chiamata a uno strumento una «firma del ragionamento»
  (`extra_content.google.thought_signature`) e la rivuole identica nei turni successivi, altrimenti risponde 400: la
  firma viaggia nel blocco dello strumento (`extra`) e torna solo a Gemini;
- Mistral ha i suoi nomi per i livelli di ragionamento."""
import json
import logging

import httpx2

from .tipi import ChiamataStrumento, ErroreModello, Fine, Testo, Uso

log = logging.getLogger(__name__)
URL_PREDEFINITO = "https://api.openai.com/v1"
URL_PER_TIPO = {"mistral": "https://api.mistral.ai/v1", "openai": URL_PREDEFINITO,
                "gemini": "https://generativelanguage.googleapis.com/v1beta/openai"}


def url_base(provider):
    return (provider.base_url or URL_PER_TIPO.get(provider.tipo, URL_PREDEFINITO)).rstrip("/")
MOTIVI = {"stop": "fine", "tool_calls": "strumenti", "length": "limite", "content_filter": "rifiuto"}


def gemini(provider):
    """Gemini, anche quando è configurato come «compatibile OpenAI» con il suo indirizzo."""
    return provider.tipo == "gemini" or "generativelanguage.googleapis.com" in (provider.base_url or "")


def _messaggi(sistema, messaggi, con_firme=False):
    risultato = [{"role": "system", "content": sistema}]
    for m in messaggi:
        if m["ruolo"] == "utente":
            if m.get("immagini_dati"):
                risultato.append({"role": "user", "content": [
                    *({"type": "image_url", "image_url": {"url": f"data:{i['mime']};base64,{i['dati']}"}} for i in m["immagini_dati"]),
                    {"type": "text", "text": m["testo"]}]})
            else:
                risultato.append({"role": "user", "content": m["testo"]})
        elif m["ruolo"] == "assistente":
            testo = "".join(b["testo"] for b in m["blocchi"] if b["tipo"] == "testo")
            chiamate = [{"id": b["id"], "type": "function",
                         "function": {"name": b["nome"], "arguments": json.dumps(b["argomenti"], ensure_ascii=False)},
                         **({"extra_content": b["extra"]} if con_firme and b.get("extra") else {})}
                        for b in m["blocchi"] if b["tipo"] == "strumento"]
            risultato.append({"role": "assistant", "content": testo or None, **({"tool_calls": chiamate} if chiamate else {})})
        elif m["ruolo"] == "strumento":
            risultato.extend({"role": "tool", "tool_call_id": r["id"], "content": r["contenuto"]}
                             for r in m["risultati"])
    return risultato


def _testo(contenuto):
    """Il testo di un delta. Alcuni modelli che ragionano (es. DeepSeek e Magistral su Mistral) mandano una lista di
    pezzi: [{"type": "thinking", ...}, {"type": "text", "text": "..."}]. Il ragionamento non va nella risposta."""
    if isinstance(contenuto, str):
        return contenuto
    if isinstance(contenuto, list):
        return "".join(p.get("text") or "" for p in contenuto if isinstance(p, dict) and p.get("type") == "text")
    return ""


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
    tipo = modello.provider.tipo
    corpo = {"model": modello.id_api, "messages": _messaggi(sistema, messaggi, con_firme=gemini(modello.provider)),
             "stream": True, "stream_options": {"include_usage": True},
             "max_completion_tokens" if tipo == "openai" else "max_tokens": min(max_token, modello.max_output)}
    if strumenti and modello.strumenti:
        corpo["tools"] = [{"type": "function", "function": {"name": s["nome"], "description": s["descrizione"],
                                                             "parameters": s["schema"]}} for s in strumenti]
    if effort == "none" and modello.provider.locale:                # Ollama: niente ragionamento, risposta subito
        corpo["reasoning_effort"] = "none"
    elif effort and modello.ragionamento:
        if tipo == "mistral":                                       # Mistral: none, low, high, xhigh, max (niente medium)
            corpo["reasoning_effort"] = {"medium": "high"}.get(effort, effort)
        elif tipo == "openai":                                      # OpenAI li ha tutti; se il modello non ne vuole uno, sotto si riprova senza
            corpo["reasoning_effort"] = effort
        else:
            corpo["reasoning_effort"] = "high" if effort in ("high", "xhigh", "max") else effort
    intestazioni = {"Content-Type": "application/json"}
    if chiave:
        intestazioni["Authorization"] = f"Bearer {chiave}"
    url = url_base(modello.provider) + "/chat/completions"
    http = http_client or httpx2.Client(timeout=httpx2.Timeout(600.0, connect=10.0))
    testo, chiamate, uso, motivo = [], {}, Uso(), "altro"
    try:
        for tentativo in range(2):
            with http.stream("POST", url, json=corpo, headers=intestazioni) as risposta:
                if risposta.status_code >= 400:
                    risposta.read()
                    if (tentativo == 0 and risposta.status_code == 400 and "reasoning_effort" in corpo
                            and "reasoning_effort" in risposta.text):
                        corpo.pop("reasoning_effort")                # livello non accettato dal modello: senza
                        log.info("%s: reasoning_effort rifiutato, riprovo senza", modello.id_api)
                        continue
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
                        pezzo_testo = _testo(delta.get("content"))
                        if pezzo_testo:
                            testo.append(pezzo_testo)
                            yield Testo(pezzo_testo)
                        for c in delta.get("tool_calls") or []:
                            voce = chiamate.setdefault(c.get("index", 0), {"id": "", "nome": "", "argomenti": ""})
                            voce["id"] = c.get("id") or voce["id"]
                            funzione = c.get("function") or {}
                            voce["nome"] += funzione.get("name") or ""
                            voce["argomenti"] += funzione.get("arguments") or ""
                            if isinstance(c.get("extra_content"), dict):         # Gemini: la firma del ragionamento
                                voce["extra"] = c["extra_content"]
                        if scelta.get("finish_reason"):
                            motivo = MOTIVI.get(scelta["finish_reason"], "altro")
            break
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
        blocchi.append({"tipo": "strumento", "id": id_chiamata, "nome": c["nome"], "argomenti": argomenti,
                        **({"extra": c["extra"]} if c.get("extra") else {})})
        yield ChiamataStrumento(id_chiamata, c["nome"], argomenti)
    if not blocchi:
        raise ErroreModello("VUOTA", "il modello non ha risposto")
    yield uso
    yield Fine("strumenti" if chiamate else motivo, blocchi)
