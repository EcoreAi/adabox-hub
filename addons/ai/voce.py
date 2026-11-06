"""Voce: dettatura con Whisper (sempre sui nostri server, l'audio non esce) e lettura delle risposte con Kokoro in
locale o con un fornitore cloud (Cartesia, Mistral, Azure, Gemini).

Verso un fornitore cloud va il testo della risposta così com'è, dati personali compresi: per questo serve un consenso
apposito dell'azienda (ai.voce_cloud), come per le immagini. Tabelle e codice non si leggono."""
import base64
import re
import struct
from xml.sax.saxutils import escape

import httpx2 as httpx
from django.core.cache import cache

from core import parametri

from .models import ServizioVoce

MASSIMO_AUDIO = 10 * 1024 * 1024
TIPI_AUDIO = ("audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/mpeg", "audio/aac")
CARATTERI_PARTE = 400
CARATTERI_PRIMA = 160                                   # la prima parte è corta: la voce parte in pochi secondi
MASSIME_PARTI = 20
TEMPO = 120


class ErroreVoce(Exception):
    pass


# ---------- impostazioni ----------

def url_locale():
    return (parametri.leggi("ai.url_voce") or "").rstrip("/")


def accesa(azienda):
    return azienda is not None and bool(parametri.leggi("ai.voce", azienda))


def dettatura_disponibile(azienda):
    return accesa(azienda) and bool(url_locale())


def servizio_per(azienda):
    """Il servizio di lettura dell'azienda: prima il suo, poi quello di tutte; i cloud solo con il consenso."""
    if not accesa(azienda):
        return None
    cloud = bool(parametri.leggi("ai.voce_cloud", azienda))
    for qs in (ServizioVoce.objects.filter(attivo=True, azienda=azienda), ServizioVoce.objects.filter(attivo=True, azienda=None)):
        for s in qs.order_by("pk"):
            if (s.locale and url_locale()) or (not s.locale and cloud):
                return s
    return None


# ---------- dettatura ----------

def trascrivi(file, lingua="", http_client=None):
    if file.size > MASSIMO_AUDIO:
        raise ErroreVoce("Registrazione troppo lunga.")
    tipo = (file.content_type or "").split(";")[0]
    if tipo not in TIPI_AUDIO:
        raise ErroreVoce("Formato audio non riconosciuto.")
    dati = {"model": parametri.leggi("ai.modello_trascrizione") or "Systran/faster-whisper-small"}
    if lingua in ("it", "en"):
        dati["language"] = lingua
    client = http_client or httpx.Client(timeout=TEMPO, trust_env=False)
    try:
        r = client.post(f"{url_locale()}/v1/audio/transcriptions", files={"file": (file.name or "voce.webm", file.read(), tipo)}, data=dati)
        r.raise_for_status()
        return str(r.json().get("text", "")).strip()
    except (httpx.HTTPError, ValueError) as e:
        raise ErroreVoce(f"La trascrizione non risponde: {type(e).__name__}") from e
    finally:
        if http_client is None:
            client.close()


# ---------- che cosa si legge ----------

_PAROLE_IT = {"il", "la", "di", "che", "e", "per", "un", "una", "non", "sono", "del", "della", "con", "le", "gli", "ho", "è", "nel"}
_PAROLE_EN = {"the", "and", "of", "to", "is", "in", "that", "for", "with", "you", "are", "this", "it", "on", "have", "be", "not"}


def lingua_di(testo):
    parole = re.findall(r"[a-zàèéìòù']+", testo.lower())
    return "en" if sum(p in _PAROLE_EN for p in parole) > sum(p in _PAROLE_IT for p in parole) else "it"


def da_leggere(markdown):
    """Il testo parlato di una risposta in Markdown: niente codice, tabelle riassunte, link senza indirizzo."""
    testo = re.sub(r"```.*?(```|$)", " Ho scritto del codice, lo trovi nella chat. ", markdown, flags=re.S)
    righe, tabella = [], 0
    for riga in testo.splitlines() + [""]:
        if riga.strip().startswith("|"):
            tabella += 1
            continue
        if tabella:
            n = max(tabella - 2, 1)
            righe.append(f"Ho preparato una tabella con {n} {'riga' if n == 1 else 'righe'}.")
            tabella = 0
        righe.append(riga)
    testo = "\n".join(righe)
    testo = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", testo)
    testo = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", testo)
    testo = re.sub(r"https?://\S+", "un link", testo)
    testo = re.sub(r"^\s{0,3}(#{1,6}|[-*+]|\d+[.)]|>)\s+", "", testo, flags=re.M)
    testo = re.sub(r"(\*\*|__|\*|_|`|~~)", "", testo)
    testo = re.sub(r"^\s*(---|\*\*\*)\s*$", "", testo, flags=re.M)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", testo)).strip()


def parti(testo):
    """Pezzi divisi tra le frasi, letti uno dopo l'altro: il primo corto (la voce parte subito), gli altri fino a
    CARATTERI_PARTE caratteri, preparati mentre si ascolta il precedente."""
    frasi = re.split(r"(?<=[.!?:;,])\s+|\n", testo)
    uscita, corrente = [], ""
    for f in (x.strip() for x in frasi):
        if not f:
            continue
        limite = CARATTERI_PARTE if uscita else CARATTERI_PRIMA
        while len(f) > limite:
            if corrente:
                uscita.append(corrente)
                corrente = ""
            taglio = f.rfind(" ", 0, limite) if f.rfind(" ", 0, limite) > 0 else limite
            uscita.append(f[:taglio])
            f = f[taglio:].strip()
            limite = CARATTERI_PARTE
        if corrente and len(corrente) + len(f) + 1 > limite:
            uscita.append(corrente)
            corrente = f
        else:
            corrente = f"{corrente} {f}".strip()
    if corrente:
        uscita.append(corrente)
    return uscita[:MASSIME_PARTI]


# ---------- lettura ----------

def _wav(pcm, frequenza=24000):
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, frequenza, frequenza * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def _controlla(r, nome):
    if r.status_code in (401, 403):
        raise ErroreVoce(f"{nome}: chiave non valida o testo rifiutato (HTTP {r.status_code}).")
    if r.status_code == 402:
        raise ErroreVoce(f"{nome}: credito esaurito.")
    if r.status_code != 200:
        raise ErroreVoce(f"{nome}: lettura non riuscita (HTTP {r.status_code}).")


def sintetizza(servizio, testo, lingua="it", http_client=None):
    """(byte, tipo MIME) dell'audio di un pezzo di testo."""
    voce = servizio.valore("voce_it" if lingua == "it" else "voce_en")
    modello = servizio.valore("modello")
    if not voce and servizio.tipo != ServizioVoce.GEMINI:
        raise ErroreVoce(f"«{servizio.nome}»: manca la voce {'italiana' if lingua == 'it' else 'inglese'}.")
    if not servizio.locale and not servizio.chiave():
        raise ErroreVoce(f"«{servizio.nome}»: manca la chiave API.")
    client = http_client or httpx.Client(timeout=TEMPO, trust_env=False, follow_redirects=False)
    try:
        if servizio.tipo == ServizioVoce.KOKORO:
            r = client.post(f"{url_locale()}/v1/audio/speech", json={"model": modello, "voice": voce, "input": testo, "response_format": "mp3"})
            _controlla(r, servizio.nome)
            return r.content, "audio/mpeg"
        if servizio.tipo == ServizioVoce.CARTESIA:
            r = client.post("https://api.cartesia.ai/tts/bytes", headers={"Authorization": f"Bearer {servizio.chiave()}", "Cartesia-Version": "2026-08-14"},
                            json={"model_id": modello, "transcript": testo, "voice": {"id": voce}, "language": lingua,
                                  "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000}})
            _controlla(r, servizio.nome)
            return r.content, "audio/mpeg"
        if servizio.tipo == ServizioVoce.MISTRAL:
            r = client.post("https://api.mistral.ai/v1/audio/speech", headers={"Authorization": f"Bearer {servizio.chiave()}"},
                            json={"model": modello, "input": testo, "voice_id": voce, "response_format": "mp3"})
            _controlla(r, servizio.nome)
            return base64.b64decode(r.json()["audio_data"]), "audio/mpeg"
        if servizio.tipo == ServizioVoce.AZURE:
            if not re.fullmatch(r"[a-z0-9]{2,30}", servizio.regione or ""):
                raise ErroreVoce(f"«{servizio.nome}»: regione Azure mancante o non valida.")
            ssml = (f"<speak version='1.0' xml:lang='{'it-IT' if lingua == 'it' else 'en-US'}'><voice name='{escape(voce)}'>"
                    f"{escape(testo)}</voice></speak>")
            r = client.post(f"https://{servizio.regione}.tts.speech.microsoft.com/cognitiveservices/v1", content=ssml.encode(),
                            headers={"Ocp-Apim-Subscription-Key": servizio.chiave(), "Content-Type": "application/ssml+xml",
                                     "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3", "User-Agent": "adabox-hub"})
            _controlla(r, servizio.nome)
            return r.content, "audio/mpeg"
        if servizio.tipo == ServizioVoce.GEMINI:
            r = client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modello}:generateContent",
                            headers={"x-goog-api-key": servizio.chiave()},
                            json={"contents": [{"parts": [{"text": testo}]}],
                                  "generationConfig": {"responseModalities": ["AUDIO"],
                                                       "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voce or "Kore"}}}}})
            _controlla(r, servizio.nome)
            parte = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
            return _wav(base64.b64decode(parte["data"])), "audio/wav"
        raise ErroreVoce("Tipo di servizio sconosciuto.")
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        raise ErroreVoce(f"«{servizio.nome}» non risponde: {type(e).__name__}") from e
    finally:
        if http_client is None:
            client.close()


def audio_di(servizio, testo, lingua):
    """Con una cache di un giorno: riascoltare una risposta non la fa pagare due volte."""
    import hashlib
    chiave = "voce:" + hashlib.sha256(f"{servizio.pk}|{servizio.valore('modello')}|{servizio.valore('voce_it')}|{servizio.valore('voce_en')}|{lingua}|{testo}".encode()).hexdigest()
    if (salvato := cache.get(chiave)) is not None:
        return salvato
    audio = sintetizza(servizio, testo, lingua)
    cache.set(chiave, audio, 86400)
    return audio
