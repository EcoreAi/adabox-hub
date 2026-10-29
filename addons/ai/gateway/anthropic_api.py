"""Adattatore per l'API Anthropic con l'SDK ufficiale (anthropic 1.x): streaming, strumenti, cache del prefisso.

I blocchi della risposta (ragionamento compreso) si rimandano invariati nei turni successivi: la storia non si
riscrive mai (richiesto dal "preserved thinking" dei modelli Claude 5.x)."""
import anthropic

from .tipi import ChiamataStrumento, ErroreModello, Fine, Testo, Uso

MOTIVI = {"end_turn": "fine", "tool_use": "strumenti", "max_tokens": "limite", "refusal": "rifiuto",
          "stop_sequence": "fine", "pause_turn": "altro"}


def _messaggi(messaggi):
    risultato = []
    for m in messaggi:
        if m["ruolo"] == "utente":
            risultato.append({"role": "user", "content": m["testo"]})
        elif m["ruolo"] == "assistente":
            nativo = m.get("nativo") or {}
            if nativo.get("provider") == "anthropic":
                contenuto = nativo["contenuto"]
            else:                                    # risposta di un altro provider (fallback): testo e strumenti
                contenuto = [{"type": "text", "text": b["testo"]} if b["tipo"] == "testo" else
                             {"type": "tool_use", "id": b["id"], "name": b["nome"], "input": b["argomenti"]}
                             for b in m["blocchi"] if b["tipo"] != "testo" or b["testo"]]
            risultato.append({"role": "assistant", "content": contenuto or [{"type": "text", "text": "…"}]})
        elif m["ruolo"] == "strumento":
            risultato.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": r["id"], "content": r["contenuto"],
                 **({"is_error": True} if r.get("errore") else {})} for r in m["risultati"]]})
    return risultato


def _strumenti(strumenti):
    definizioni = [{"name": s["nome"], "description": s["descrizione"], "input_schema": s["schema"]}
                   for s in strumenti]
    if definizioni:
        definizioni[-1] = {**definizioni[-1], "cache_control": {"type": "ephemeral"}}   # prefisso: strumenti
    return definizioni


def _errore(e):
    if isinstance(e, anthropic.RateLimitError):
        attesa = e.response.headers.get("retry-after") if e.response is not None else None
        return ErroreModello("RATE_LIMIT", str(e), float(attesa) if attesa and attesa.replace(".", "").isdigit() else None)
    if isinstance(e, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return ErroreModello("AUTENTICAZIONE", "chiave API non valida o senza permessi")
    if isinstance(e, anthropic.BadRequestError):
        testo = str(e)
        return ErroreModello("CONTESTO" if "too long" in testo or "context" in testo.lower() else "RICHIESTA", testo)
    if isinstance(e, anthropic.APITimeoutError):
        return ErroreModello("TIMEOUT", str(e))
    if isinstance(e, anthropic.APIConnectionError):
        return ErroreModello("RETE", str(e))
    if isinstance(e, anthropic.APIStatusError):
        return ErroreModello("SERVER" if e.status_code >= 500 or e.status_code == 529 else "RICHIESTA", str(e))
    return ErroreModello("SERVER", str(e))


def client(chiave, base_url="", http_client=None):
    argomenti = {"api_key": chiave, "max_retries": 0, "timeout": 600.0}
    if base_url:
        argomenti["base_url"] = base_url
    if http_client is not None:
        argomenti["http_client"] = http_client
    return anthropic.Anthropic(**argomenti)


def flusso(modello, chiave, *, sistema, messaggi, strumenti=(), max_token=16000, effort="", http_client=None):
    parametri = {
        "model": modello.id_api, "max_tokens": min(max_token, modello.max_output),
        "system": [{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
        "messages": _messaggi(messaggi),
    }
    if strumenti and modello.strumenti:
        parametri["tools"] = _strumenti(strumenti)
    if effort and modello.ragionamento:
        parametri["output_config"] = {"effort": effort}
    try:
        with client(chiave, modello.provider.base_url, http_client).messages.stream(**parametri) as stream:
            for evento in stream:
                if evento.type == "text" and evento.text:
                    yield Testo(evento.text)
            finale = stream.get_final_message()
    except anthropic.APIError as e:
        raise _errore(e) from e
    contenuto = finale.to_dict()["content"]
    blocchi = []
    for b in finale.content:
        if b.type == "text":
            blocchi.append({"tipo": "testo", "testo": b.text})
        elif b.type == "tool_use":
            blocchi.append({"tipo": "strumento", "id": b.id, "nome": b.name, "argomenti": dict(b.input or {})})
            yield ChiamataStrumento(b.id, b.name, dict(b.input or {}))
    u = finale.usage
    yield Uso(input=u.input_tokens or 0, output=u.output_tokens or 0,
              cache_scrittura=getattr(u, "cache_creation_input_tokens", 0) or 0,
              cache_lettura=getattr(u, "cache_read_input_tokens", 0) or 0)
    yield Fine(MOTIVI.get(finale.stop_reason, "altro"), blocchi, {"provider": "anthropic", "contenuto": contenuto})
