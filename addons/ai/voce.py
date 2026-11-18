"""Voce: dettatura con Whisper (sempre sui nostri server, l'audio non esce) e lettura delle risposte con Kokoro in
locale o con un fornitore cloud (Cartesia, Mistral, Azure, Gemini).

Verso un fornitore cloud va il testo della risposta così com'è, dati personali compresi: per questo serve un consenso
apposito dell'azienda (ai.voce_cloud), come per le immagini. Tabelle e codice non si leggono."""
import base64
import logging
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
    from . import funzioni
    return azienda is not None and funzioni.attiva("voce") and bool(parametri.leggi("ai.voce", azienda))


def dettatura_disponibile(azienda):
    return accesa(azienda) and (bool(url_locale()) or trascrizione_cloud(azienda) is not None)


def trascrizione_cloud(azienda):
    """Il servizio che trascrive in cloud per l'azienda (il suo, poi quello di tutte), solo con il consenso: l'audio
    di chi parla esce dal server. None = Whisper locale."""
    if not accesa(azienda) or not parametri.leggi("ai.trascrizione_cloud", azienda):
        return None
    base = ServizioVoce.objects.filter(attivo=True, uso=ServizioVoce.TRASCRIZIONE)
    for qs in (base.filter(azienda=azienda), base.filter(azienda=None)):
        servizio = qs.order_by("pk").first()
        if servizio is not None:
            return servizio
    return None


def servizio_per(azienda, solo_locale=False):
    """Il servizio di lettura dell'azienda: prima il suo, poi quello di tutte; i cloud solo con il consenso e mai con
    `solo_locale` (chat riservate)."""
    if not accesa(azienda):
        return None
    cloud = bool(parametri.leggi("ai.voce_cloud", azienda))
    lettura = ServizioVoce.objects.filter(attivo=True, uso=ServizioVoce.LETTURA)
    for qs in (lettura.filter(azienda=azienda), lettura.filter(azienda=None)):
        for s in qs.order_by("pk"):
            if (s.locale and url_locale()) or (not s.locale and cloud and not solo_locale):
                return s
    return None


# ---------- dettatura ----------

OVH_URL = "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"
TEMPO_CLOUD = 30
log = logging.getLogger(__name__)


def parole_note(utente, azienda):
    """Le parole da riconoscere anche se rare: il nome dell'assistente, il marchio, l'azienda e il nome dell'utente.
    Senza, «Ada, quali appuntamenti…» diventava «Ha da quali…»."""
    from django.conf import settings
    parole = ["Ada", getattr(settings, "THEME", {}).get("brand", ""), getattr(azienda, "nome", ""),
              getattr(utente, "first_name", ""), getattr(utente, "last_name", "")]
    visti, uniche = set(), []
    for p in parole:
        p = " ".join(str(p or "").split())[:40]
        if p and p.lower() not in visti:
            visti.add(p.lower())
            uniche.append(p)
    return uniche[:10]


def trascrivi(file, lingua="", http_client=None, azienda=None, parole=()):
    """Il testo detto: con il servizio cloud dell'azienda se c'è (e se non risponde, con il Whisper locale), altrimenti
    con il Whisper locale."""
    if file.size > MASSIMO_AUDIO:
        raise ErroreVoce("Registrazione troppo lunga.")
    tipo = (file.content_type or "").split(";")[0]
    if tipo not in TIPI_AUDIO:
        raise ErroreVoce("Formato audio non riconosciuto.")
    servizio = trascrizione_cloud(azienda) if azienda is not None else None
    if servizio is not None:
        dati_audio = file.read()
        try:
            return trascrivi_cloud(servizio, dati_audio, file.name or "voce.webm", tipo, lingua, http_client, parole=parole)
        except ErroreVoce:
            if not url_locale():
                raise
            log.warning("trascrizione con «%s» non riuscita: si usa il Whisper locale", servizio.nome, exc_info=True)
            file.seek(0)
    if not url_locale():
        raise ErroreVoce("La dettatura non è configurata.")
    return _trascrivi_locale(file, tipo, lingua, http_client)


def trascrivi_cloud(servizio, audio, nome, tipo, lingua="", http_client=None, parole=()):
    """Mistral Voxtral e OVH (Whisper) parlano la stessa lingua di OpenAI: multipart con file, modello e lingua."""
    if not servizio.chiave():
        raise ErroreVoce(f"«{servizio.nome}»: manca la chiave API.")
    url = {ServizioVoce.MISTRAL: "https://api.mistral.ai/v1", ServizioVoce.OVH: OVH_URL}.get(servizio.tipo)
    if url is None:
        raise ErroreVoce(f"«{servizio.nome}» non trascrive.")
    dati = {"model": servizio.valore("modello")}
    if lingua in ("it", "en"):
        dati["language"] = lingua
    client = http_client or httpx.Client(timeout=TEMPO_CLOUD, trust_env=False, follow_redirects=False)
    try:
        file = [("file", (nome, audio, tipo))]
        if servizio.tipo == ServizioVoce.MISTRAL:          # Voxtral: parole da favorire (nomi propri, marchi)
            file += [("context_bias", (None, p)) for p in parole]
        r = client.post(f"{url}/audio/transcriptions", headers={"Authorization": f"Bearer {servizio.chiave()}"},
                        files=file, data=dati)
        _controlla(r, servizio.nome, "trascrizione")
        return str(r.json().get("text", "")).strip()
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        raise ErroreVoce(f"«{servizio.nome}» non risponde: {type(e).__name__}") from e
    finally:
        if http_client is None:
            client.close()


def _trascrivi_locale(file, tipo, lingua, http_client):
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

_PAROLE_IT = {"il", "la", "di", "che", "e", "per", "un", "una", "non", "sono", "del", "della", "con", "le", "gli", "ho", "è", "nel",
              "hai", "oggi", "ci", "al", "alle", "dei", "delle", "questo", "questa", "mi", "ti", "si", "anche", "più", "ora"}
# niente parole che esistono anche in italiano («in», «a»): con «Oggi hai sei appuntamenti in calendario» vinceva l'inglese
_PAROLE_EN = {"the", "and", "of", "to", "is", "that", "for", "with", "you", "are", "this", "it", "on", "have", "be", "not"}


def lingua_di(testo):
    """«en» solo se l'inglese è evidente (almeno tre parole tipiche e il doppio delle italiane): i clienti sono
    italiani, e un pezzo breve letto con la voce inglese suona sbagliato."""
    parole = re.findall(r"[a-zàèéìòù']+", testo.lower())
    inglesi, italiane = sum(p in _PAROLE_EN for p in parole), sum(p in _PAROLE_IT for p in parole)
    return "en" if inglesi >= 3 and inglesi > 2 * italiane else "it"


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
    testo = per_la_voce(testo)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", testo)).strip()


MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")


def per_la_voce(testo):
    """Le cifre come si dicono: il testo resta in cifre (la guardia sui numeri le controlla), la voce le pronuncia.
    13:30 → «13 e 30», 1.250,50 € → «1250 euro e 50», 16/11/2026 → «16 novembre 2026», 12% → «12 per cento»;
    le emoji non si leggono."""
    testo = EMOJI.sub("", testo)
    # gli indirizzi email come si dicono: passati così, la voce li compitava con suoni inglesi
    testo = re.sub(r"\b([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)\b",
                   lambda m: f"{m.group(1).replace('.', ' punto ')} chiocciola {m.group(2).replace('.', ' punto ')}", testo)

    def importo(m):
        intero, cent = m.group("intero").replace(".", ""), (m.group("cent") or "").ljust(2, "0") if m.group("cent") else ""
        return f"{intero} euro" + (f" e {int(cent)}" if cent and int(cent) else "")
    soldi = r"(?P<intero>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<cent>\d{1,2}))?"
    testo = re.sub(r"€\s?" + soldi, importo, testo)
    testo = re.sub(soldi + r"\s?(?:€|euro\b|EUR\b)", importo, testo)

    def data(m):
        g, mese, anno = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= g <= 31 and 1 <= mese <= 12):
            return m.group(0)
        return f"{g} {MESI[mese - 1]}" + (f" {anno if len(anno) == 4 else '20' + anno}" if anno else "")
    testo = re.sub(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?\b", data, testo)
    testo = re.sub(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b(?![.,]\d)",
                   lambda m: f"{int(m.group(1))}" + (f" e {int(m.group(2))}" if int(m.group(2)) else ""), testo)
    testo = re.sub(r"\b\d{1,3}(?:\.\d{3})+\b", lambda m: m.group(0).replace(".", ""), testo)
    testo = re.sub(r"(\d),(\d)", r"\1 virgola \2", testo)
    testo = re.sub(r"\s?%", " per cento", testo)
    # simboli che la voce leggerebbe: «#12» è «numero 12», le barre sono pause o spazi, «&» è «e»
    testo = re.sub(r"#\s?(\d+)", r"numero \1", testo).replace("#", "")
    testo = re.sub(r"\s+/\s+", ", ", testo)
    testo = re.sub(r"\s*&\s*", " e ", testo)
    return testo.replace("/", " ")


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

def silenzio_wav(secondi=1, frequenza=16000):
    """Un breve WAV muto, per provare un servizio di trascrizione senza mandare la voce di nessuno."""
    return _wav(b"\x00\x00" * int(secondi * frequenza), frequenza)


def _wav(pcm, frequenza=24000):
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, frequenza, frequenza * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def _controlla(r, nome, azione="lettura"):
    if r.status_code in (401, 403):
        raise ErroreVoce(f"{nome}: chiave non valida o richiesta rifiutata (HTTP {r.status_code}).")
    if r.status_code == 402:
        raise ErroreVoce(f"{nome}: credito esaurito.")
    if r.status_code != 200:
        raise ErroreVoce(f"{nome}: {azione} non riuscita (HTTP {r.status_code}).")


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
