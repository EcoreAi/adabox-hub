"""Trascrizione del parlato in cloud (Mistral Voxtral, OVH Whisper): solo con il consenso dell'azienda, con il
Whisper locale come riserva; i servizi di trascrizione non leggono le risposte e viceversa."""
import httpx2 as httpx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from ai import voce
from ai.forms import ServizioVoceForm
from ai.models import ServizioVoce
from core import cifratura
from core.models import Azienda


@pytest.fixture
def s(db, monkeypatch):
    a = Azienda.objects.first()
    valori = {"ai.voce": True, "ai.voce_cloud": False, "ai.trascrizione_cloud": False, "ai.url_voce": "http://speaches:8000",
              "ai.modello_trascrizione": "Systran/faster-whisper-small"}
    originale = voce.parametri.leggi
    monkeypatch.setattr(voce.parametri, "leggi", lambda chiave, azienda=None: valori[chiave] if chiave in valori else originale(chiave, azienda))
    return {"az": a, "valori": valori}


def _audio():
    return SimpleUploadedFile("v.webm", b"audio", content_type="audio/webm;codecs=opus")


def _client(viste, risposte):
    def gestisci(richiesta):
        viste.append(richiesta)
        stato, corpo = risposte(richiesta)
        return httpx.Response(stato, json=corpo)
    return httpx.Client(transport=httpx.MockTransport(gestisci))


def _mistral():
    return ServizioVoce.objects.create(nome="Voxtral", tipo=ServizioVoce.MISTRAL, uso=ServizioVoce.TRASCRIZIONE,
                                       chiave_cifrata=cifratura.cifra("chiave-mistral"))


def test_senza_consenso_resta_il_whisper_locale(s):
    _mistral()
    viste = []
    testo = voce.trascrivi(_audio(), "it", _client(viste, lambda r: (200, {"text": "locale"})), azienda=s["az"])
    assert testo == "locale" and str(viste[0].url) == "http://speaches:8000/v1/audio/transcriptions"


def test_mistral_con_il_consenso(s):
    _mistral()
    s["valori"]["ai.trascrizione_cloud"] = True
    viste = []
    testo = voce.trascrivi(_audio(), "it", _client(viste, lambda r: (200, {"text": " quante fatture "})), azienda=s["az"])
    r = viste[0]
    corpo = r.read().decode(errors="replace")
    assert testo == "quante fatture" and str(r.url) == "https://api.mistral.ai/v1/audio/transcriptions"
    assert r.headers["Authorization"] == "Bearer chiave-mistral"
    assert "voxtral-mini-latest" in corpo and 'name="language"' in corpo and "audio/webm" in corpo


def test_ovh_con_il_suo_modello(s):
    ServizioVoce.objects.create(nome="OVH", tipo=ServizioVoce.OVH, uso=ServizioVoce.TRASCRIZIONE, chiave_cifrata=cifratura.cifra("tok"))
    s["valori"]["ai.trascrizione_cloud"] = True
    viste = []
    voce.trascrivi(_audio(), "it", _client(viste, lambda r: (200, {"text": "ok"})), azienda=s["az"])
    assert str(viste[0].url) == f"{voce.OVH_URL}/audio/transcriptions" and "whisper-large-v3-turbo" in viste[0].read().decode(errors="replace")


def test_se_il_cloud_non_risponde_si_usa_il_locale(s):
    _mistral()
    s["valori"]["ai.trascrizione_cloud"] = True
    viste = []
    risposte = lambda r: (500, {}) if "mistral" in str(r.url) else (200, {"text": "dal locale"})  # noqa: E731
    assert voce.trascrivi(_audio(), "it", _client(viste, risposte), azienda=s["az"]) == "dal locale"
    assert [r.url.host for r in viste] == ["api.mistral.ai", "speaches"]
    assert b"audio" in viste[1].read()                                          # il file si rilegge da capo
    s["valori"]["ai.url_voce"] = ""
    with pytest.raises(voce.ErroreVoce, match="trascrizione non riuscita"):
        voce.trascrivi(_audio(), "it", _client([], lambda r: (500, {})), azienda=s["az"])


def test_dettatura_anche_solo_in_cloud_e_lettura_separata(s):
    s["valori"]["ai.url_voce"] = ""
    assert not voce.dettatura_disponibile(s["az"])
    _mistral()
    s["valori"]["ai.trascrizione_cloud"] = True
    assert voce.dettatura_disponibile(s["az"])
    s["valori"]["ai.voce_cloud"] = True
    assert voce.servizio_per(s["az"]) is None                                   # un servizio di trascrizione non legge
    lettura = ServizioVoce.objects.create(nome="Voxtral TTS", tipo=ServizioVoce.MISTRAL, chiave_cifrata=cifratura.cifra("k"))
    assert voce.servizio_per(s["az"]) == lettura and voce.trascrizione_cloud(s["az"]).nome == "Voxtral"
    s["valori"]["ai.voce"] = False
    assert voce.trascrizione_cloud(s["az"]) is None


def test_modulo_tipi_ammessi_per_uso_e_chiave(db):
    def form(**dati):
        return ServizioVoceForm(data={"nome": "x", "attivo": "on", **dati})
    f = form(tipo="ovh", uso="lettura", nuova_chiave="k")
    assert not f.is_valid() and "tipo" in f.errors
    f = form(tipo="kokoro", uso="trascrizione")
    assert not f.is_valid() and "tipo" in f.errors
    f = form(tipo="mistral", uso="trascrizione")
    assert not f.is_valid() and "nuova_chiave" in f.errors
    f = form(tipo="ovh", uso="trascrizione", nuova_chiave="tok")
    assert f.is_valid(), f.errors
    servizio = f.save()
    assert servizio.chiave() == "tok" and servizio.valore("modello") == "whisper-large-v3-turbo" and servizio.valore("voce_it") == ""


def test_prova_con_un_secondo_di_silenzio(db):
    servizio = ServizioVoce.objects.create(nome="Voxtral", tipo=ServizioVoce.MISTRAL, uso=ServizioVoce.TRASCRIZIONE,
                                           chiave_cifrata=cifratura.cifra("k"))
    viste = []
    wav = voce.silenzio_wav()
    assert wav[:4] == b"RIFF" and len(wav) > 30000
    assert voce.trascrivi_cloud(servizio, wav, "prova.wav", "audio/wav", "it", _client(viste, lambda r: (200, {"text": ""}))) == ""
    with pytest.raises(voce.ErroreVoce, match="chiave non valida"):
        voce.trascrivi_cloud(servizio, wav, "prova.wav", "audio/wav", "it", _client([], lambda r: (401, {})))


def test_parole_da_favorire_solo_per_mistral(s):
    from django.contrib.auth.models import User
    u = User(first_name="Enrico", last_name="Corellas", username="ec")
    parole = voce.parole_note(u, s["az"])
    assert parole[0] == "Ada" and "Enrico" in parole and "Corellas" in parole and len(parole) == len({p.lower() for p in parole})
    assert not any(" " in p or "," in p for p in parole)                       # Mistral rifiuta (400) spazi e virgole
    _mistral()
    s["valori"]["ai.trascrizione_cloud"] = True
    viste = []
    voce.trascrivi(_audio(), "it", _client(viste, lambda r: (200, {"text": "ok"})), azienda=s["az"], parole=["Ada", "Enrico"])
    corpo = viste[0].read().decode(errors="replace")
    assert corpo.count('name="context_bias"') == 2 and "Enrico" in corpo
    ovh = ServizioVoce.objects.create(nome="OVH", tipo=ServizioVoce.OVH, uso=ServizioVoce.TRASCRIZIONE, chiave_cifrata=cifratura.cifra("t"))
    viste = []
    voce.trascrivi_cloud(ovh, b"x", "v.webm", "audio/webm", "it", _client(viste, lambda r: (200, {"text": "ok"})), parole=["Ada"])
    assert "context_bias" not in viste[0].read().decode(errors="replace")       # OVH non lo conosce


def test_parole_divise_e_prompt_al_whisper_locale(s, settings):
    """«Adabox v3» con lo spazio faceva rispondere 400 a Mistral su ogni trascrizione."""
    from django.contrib.auth.models import User
    settings.THEME = {**settings.THEME, "brand": "Adabox v3"}
    parole = voce.parole_note(User(first_name="Enrico", username="e"), s["az"])
    assert "Adabox" in parole and "v3" not in parole and not any(" " in p for p in parole)
    viste = []
    from django.core.files.uploadedfile import SimpleUploadedFile
    voce._trascrivi_locale(SimpleUploadedFile("v.webm", b"x", "audio/webm"), "audio/webm", "it",
                           _client(viste, lambda r: (200, {"text": "ciao Ada"})), ["Ada", "Enrico"])
    assert 'name="prompt"' in viste[0].read().decode(errors="replace")
