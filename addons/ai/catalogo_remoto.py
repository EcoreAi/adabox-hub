"""Il catalogo dei modelli letto dal provider (GET /models di OpenAI, Gemini, Mistral e degli endpoint compatibili),
per aggiungere i modelli senza scriverli a mano. Mistral dà contesto e capacità; OpenRouter anche i prezzi; OpenAI,
Gemini e Ollama solo l'ID. I prezzi che il provider non dà restano da scrivere nella scheda del modello."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx2

from .gateway.openai_compat import url_base
from .models import Modello, Provider

HTTP = None                      # nei test: un httpx2.Client con un trasporto finto
CON_CATALOGO = (Provider.OPENAI, Provider.GEMINI, Provider.MISTRAL, Provider.OPENAI_COMPAT)
# OpenAI e Gemini elencano insieme ai modelli di chat anche quelli per immagini, voce, embedding: dal nome si riconoscono
NON_DI_CHAT = ("embedding", "tts", "whisper", "transcribe", "audio", "realtime", "image", "imagen", "dall-e", "veo", "sora",
               "moderation", "aqa", "babbage", "davinci")


class CatalogoNonDisponibile(Exception):
    pass


@dataclass
class Voce:
    id_api: str
    nome: str
    descrizione: str = ""
    contesto: int = 0
    strumenti: bool = True
    visione: bool = False
    prezzo_input: Decimal = None
    prezzo_output: Decimal = None
    alias: tuple = ()
    presente: bool = False


def _per_milione(valore):
    """OpenRouter dà i prezzi in dollari per token, come stringa."""
    try:
        prezzo = Decimal(str(valore)) * 1_000_000
    except (InvalidOperation, TypeError):
        return None
    return prezzo.quantize(Decimal("0.0001")) if prezzo >= 0 else None


def _nome(id_api):
    return id_api.replace("-", " ").replace("_", " ").strip().title()[:80]


def leggi(provider, azienda=None):
    """[Voce] dei modelli di chat del provider, i dismessi esclusi e gli alias raccolti sotto un solo nome."""
    if provider.tipo not in CON_CATALOGO:
        raise CatalogoNonDisponibile("Il catalogo si legge da OpenAI, Gemini, Mistral e dai provider compatibili OpenAI.")
    chiave = provider.chiave_per(azienda)
    if provider.tipo != Provider.OPENAI_COMPAT and not chiave:
        raise CatalogoNonDisponibile(f"Inserisci prima la chiave API di {provider.get_tipo_display()} nel provider.")
    con_nomi_misti = provider.tipo in (Provider.OPENAI, Provider.GEMINI)
    intestazioni = {"Authorization": f"Bearer {chiave}"} if chiave else {}
    http = HTTP or httpx2.Client(timeout=httpx2.Timeout(30.0, connect=10.0))
    try:
        risposta = http.get(url_base(provider) + "/models", headers=intestazioni)
    except httpx2.HTTPError as e:
        raise CatalogoNonDisponibile(f"Il provider non risponde: {e}") from e
    finally:
        if HTTP is None:
            http.close()
    if risposta.status_code in (401, 403):
        raise CatalogoNonDisponibile("Chiave API non valida o senza permessi.")
    if risposta.status_code >= 400:
        raise CatalogoNonDisponibile(f"Il provider ha risposto con un errore ({risposta.status_code}).")
    try:
        dati = risposta.json()
    except ValueError as e:
        raise CatalogoNonDisponibile("Risposta del provider non leggibile.") from e
    elenco = dati.get("data", []) if isinstance(dati, dict) else dati
    presenti = set(Modello.objects.filter(provider=provider).values_list("id_api", flat=True))
    voci, visti = [], set()
    for m in elenco if isinstance(elenco, list) else []:
        if not isinstance(m, dict) or not m.get("id") or m.get("archived") or m.get("deprecation"):
            continue
        m = {**m, "id": m["id"].removeprefix("models/")}                    # Gemini li chiama «models/gemini-…»
        if con_nomi_misti and any(parola in m["id"].lower() for parola in NON_DI_CHAT):
            continue
        capacita = m.get("capabilities") or {}
        if capacita and not capacita.get("completion_chat", True):          # embedding, OCR, moderazione...
            continue
        alias = tuple(a for a in (m.get("aliases") or []) if a != m["id"])
        if m["id"] in visti:
            continue
        visti.update((m["id"], *alias))
        prezzi = m.get("pricing") or {}
        voci.append(Voce(
            id_api=m["id"], nome=(m.get("name") or _nome(m["id"]))[:80], descrizione=(m.get("description") or "")[:300],
            contesto=int(m.get("max_context_length") or m.get("context_length") or 0),
            strumenti=bool(capacita.get("function_calling", True)), visione=bool(capacita.get("vision", False)),
            prezzo_input=_per_milione(prezzi["prompt"]) if "prompt" in prezzi else None,
            prezzo_output=_per_milione(prezzi["completion"]) if "completion" in prezzi else None,
            alias=alias, presente=m["id"] in presenti or bool(presenti.intersection(alias))))
    return sorted(voci, key=lambda v: (v.presente, v.nome.lower()))


def importa(provider, voci, scelti):
    """Crea i modelli scelti (quelli già presenti si aggiornano solo in contesto e capacità). Restituisce (nuovi, aggiornati)."""
    nuovi = aggiornati = 0
    for v in voci:
        if v.id_api not in scelti:
            continue
        modello = Modello.objects.filter(provider=provider, id_api=v.id_api).first()
        capacita = {"strumenti": v.strumenti, "visione": v.visione}
        if v.contesto:
            capacita["contesto"] = v.contesto
        if modello is not None:
            for campo, valore in capacita.items():
                setattr(modello, campo, valore)
            modello.save()
            aggiornati += 1
            continue
        Modello.objects.create(provider=provider, id_api=v.id_api, etichetta=v.nome, prezzo_input=v.prezzo_input,
                               prezzo_output=v.prezzo_output, residenza_ue=provider.tipo == Provider.MISTRAL,
                               max_output=min(v.contesto, 32_000) if v.contesto else 8192,
                               **{"contesto": 128_000, **capacita})
        nuovi += 1
    return nuovi, aggiornati
