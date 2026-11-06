"""Voce: dettatura con Whisper locale, lettura con Kokoro o con un fornitore cloud solo se l'azienda lo permette."""
import base64
import json

import httpx2 as httpx
import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ai import voce
from ai.models import Conversazione, MessaggioChat, ServizioVoce
from core import cifratura
from core.models import Azienda


@pytest.fixture
def s(db, client, monkeypatch, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    a, b = Azienda.objects.first(), Azienda.objects.create(nome="Altra")
    u = User.objects.create_user("anna", password="x")
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    u.profilo.aziende.set([a])
    u.profilo.azienda_predefinita = a
    u.profilo.save()
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    valori = {"ai.voce": True, "ai.voce_cloud": False, "ai.url_voce": "http://speaches:8000", "ai.modello_trascrizione": "Systran/faster-whisper-small"}
    originale = voce.parametri.leggi
    monkeypatch.setattr(voce.parametri, "leggi", lambda chiave, azienda=None: valori[chiave] if chiave in valori else originale(chiave, azienda))
    return {"u": u, "az": a, "altra": b, "valori": valori}


def _client(gestore, viste):
    def registra(r):
        viste.append(r)
        return gestore(r)
    return httpx.Client(transport=httpx.MockTransport(registra))


def test_testo_da_leggere_e_parti():
    md = "## Riepilogo\nEcco **i dati** dal [gestionale](https://x.it/a).\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n```python\nprint(1)\n```\n- punto uno\nVedi https://y.it/z"
    t = voce.da_leggere(md)
    assert "Riepilogo" in t and "i dati dal gestionale" in t and "tabella con 2 righe" in t and "codice" in t
    assert "print" not in t and "https" not in t and "**" not in t and "|" not in t and "punto uno" in t
    pezzi = voce.parti(("Frase abbastanza lunga da contare. " * 60).strip())
    assert all(len(p) <= voce.CARATTERI_PARTE for p in pezzi) and len(pezzi) > 1 and len(pezzi[0]) <= voce.CARATTERI_PRIMA
    assert " ".join(pezzi).split() == ("Frase abbastanza lunga da contare. " * 60).split()      # niente perso o ripetuto
    assert "" not in voce.parti("y" * voce.CARATTERI_PRIMA + ". Seconda frase.")
    lunga = voce.parti("x" * 1000)
    assert len(lunga[0]) == voce.CARATTERI_PRIMA and "".join(lunga) == "x" * 1000
    assert voce.lingua_di("The order is late and we are sorry for that") == "en"
    assert voce.lingua_di("L'ordine è in ritardo e ci scusiamo per il disagio") == "it"


def test_quale_servizio(s):
    assert voce.servizio_per(s["az"]) is None
    cloud = ServizioVoce.objects.create(nome="Mistral", tipo="mistral", chiave_cifrata=cifratura.cifra("k"))
    assert voce.servizio_per(s["az"]) is None                       # cloud senza consenso
    s["valori"]["ai.voce_cloud"] = True
    assert voce.servizio_per(s["az"]) == cloud
    s["valori"]["ai.voce_cloud"] = False
    kokoro = ServizioVoce.objects.create(nome="Kokoro", tipo="kokoro")
    assert voce.servizio_per(s["az"]) == kokoro
    s["valori"]["ai.url_voce"] = ""
    assert voce.servizio_per(s["az"]) is None and not voce.dettatura_disponibile(s["az"])
    s["valori"]["ai.url_voce"] = "http://speaches:8000"
    propria = ServizioVoce.objects.create(nome="Kokoro A", tipo="kokoro", azienda=s["az"])
    assert voce.servizio_per(s["az"]) == propria and voce.servizio_per(s["altra"]) == kokoro
    s["valori"]["ai.voce"] = False
    assert voce.servizio_per(s["az"]) is None and not voce.dettatura_disponibile(s["az"])


@pytest.mark.parametrize("tipo,url,controllo", [
    ("kokoro", "http://speaches:8000/v1/audio/speech", lambda r, c: c["voice"] == "if_sara" and c["model"].startswith("speaches-ai/Kokoro")),
    ("cartesia", "https://api.cartesia.ai/tts/bytes", lambda r, c: r.headers["cartesia-version"] == "2026-08-14" and c["voice"] == {"id": "v-it"}
     and c["model_id"] == "sonic-3.6" and r.headers["authorization"] == "Bearer k"),
    ("mistral", "https://api.mistral.ai/v1/audio/speech", lambda r, c: c["voice_id"] == "voice_482" and c["model"] == "voxtral-mini-tts-3-0"),
    ("azure", "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1", lambda r, c: b"it-IT-IsabellaNeural" in r.content
     and b"&lt;b&gt;" in r.content and r.headers["ocp-apim-subscription-key"] == "k"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-tts-preview:generateContent",
     lambda r, c: c["generationConfig"]["responseModalities"] == ["AUDIO"] and r.headers["x-goog-api-key"] == "k"),
])
def test_richieste_dei_fornitori(s, tipo, url, controllo):
    servizio = ServizioVoce.objects.create(nome=tipo, tipo=tipo, regione="westeurope", voce_it="v-it" if tipo == "cartesia" else "",
                                           voce_en="v-en" if tipo == "cartesia" else "", chiave_cifrata=cifratura.cifra("k"))

    def gestore(r):
        if tipo == "mistral":
            return httpx.Response(200, json={"audio_data": base64.b64encode(b"MP3").decode()})
        if tipo == "gemini":
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/pcm", "data": base64.b64encode(b"\0\0" * 10).decode()}}]}}]})
        return httpx.Response(200, content=b"MP3")
    viste = []
    audio, mime = voce.sintetizza(servizio, "Ciao <b>", "it", http_client=_client(gestore, viste))
    r = viste[0]
    corpo = json.loads(r.content) if r.headers.get("content-type", "").startswith("application/json") else {}
    assert str(r.url) == url and controllo(r, corpo)
    if tipo == "gemini":
        assert mime == "audio/wav" and audio[:4] == b"RIFF" and audio[24:28] == (24000).to_bytes(4, "little")
    else:
        assert audio == b"MP3" and mime == "audio/mpeg"


def test_errori_dei_fornitori(s):
    servizio = ServizioVoce.objects.create(nome="Cart", tipo="cartesia", voce_it="a", voce_en="b", chiave_cifrata=cifratura.cifra("k"))
    with pytest.raises(voce.ErroreVoce, match="credito"):
        voce.sintetizza(servizio, "x", http_client=_client(lambda r: httpx.Response(402), []))
    senza = ServizioVoce.objects.create(nome="Senza", tipo="mistral")
    with pytest.raises(voce.ErroreVoce, match="chiave"):
        voce.sintetizza(senza, "x")


def test_dettatura(s, client, monkeypatch):
    viste = []
    finto = _client(lambda r: httpx.Response(200, json={"text": " Ciao Ada "}), viste)
    monkeypatch.setattr(voce, "trascrivi", lambda file, lingua="", _v=voce.trascrivi: _v(file, lingua, http_client=finto))
    r = client.post(reverse("ai:trascrivi_voce"), {"audio": SimpleUploadedFile("v.webm", b"x" * 100, content_type="audio/webm;codecs=opus")})
    assert r.json() == {"testo": "Ciao Ada"} and str(viste[0].url) == "http://speaches:8000/v1/audio/transcriptions"
    assert b"faster-whisper-small" in viste[0].content
    r = client.post(reverse("ai:trascrivi_voce"), {"audio": SimpleUploadedFile("v.exe", b"x", content_type="application/x-msdownload")})
    assert r.status_code == 502 and "Formato" in r.json()["errore"]
    s["valori"]["ai.voce"] = False
    assert client.post(reverse("ai:trascrivi_voce"), {"audio": SimpleUploadedFile("v.webm", b"x", content_type="audio/webm")}).status_code == 400


def test_lettura_di_una_risposta_con_cache(s, client, monkeypatch):
    ServizioVoce.objects.create(nome="Kokoro", tipo="kokoro")
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    m = MessaggioChat.objects.create(conversazione=c, ruolo="assistente", testo="Buongiorno. " + "Il magazzino è in ordine. " * 40)
    chiamate = []
    monkeypatch.setattr(voce, "sintetizza", lambda servizio, testo, lingua, http_client=None: chiamate.append((testo, lingua)) or (b"MP3", "audio/mpeg"))
    n = client.get(reverse("ai:parti_voce", args=[m.pk])).json()["parti"]
    assert n >= 2
    r = client.get(reverse("ai:audio_voce", args=[m.pk, 0]))
    assert r.content == b"MP3" and r["Content-Type"] == "audio/mpeg" and chiamate[0][1] == "it"
    client.get(reverse("ai:audio_voce", args=[m.pk, 0]))
    assert len(chiamate) == 1                                            # riascoltare non si paga due volte
    assert client.get(reverse("ai:audio_voce", args=[m.pk, n])).status_code == 404
    altro = User.objects.create_user("bruno", password="x")
    altro.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    client.force_login(altro)
    assert client.get(reverse("ai:audio_voce", args=[m.pk, 0])).status_code == 404


def test_bottoni_solo_se_attivi(s, client):
    pagina = client.get(reverse("ai:chat")).content
    assert b"data-microfono" in pagina and b"data-voce-automatica" not in pagina   # niente servizio di lettura
    ServizioVoce.objects.create(nome="Kokoro", tipo="kokoro")
    pagina = client.get(reverse("ai:chat")).content
    assert b"data-voce-automatica" in pagina and b"data-lettura" in pagina
    s["valori"]["ai.voce"] = False
    pagina = client.get(reverse("ai:chat")).content
    assert b"data-microfono" not in pagina and b"data-lettura" not in pagina


def test_form_del_servizio(s, client):
    r = client.post(reverse("ai:voce_nuovo"), {"nome": "Az", "tipo": "azure", "attivo": "on", "nuova_chiave": "k"})
    assert r.status_code == 200 and not ServizioVoce.objects.exists()           # manca la regione
    client.post(reverse("ai:voce_nuovo"), {"nome": "Az", "tipo": "azure", "regione": "westeurope", "attivo": "on", "nuova_chiave": "segreta"})
    sv = ServizioVoce.objects.get()
    assert sv.chiave() == "segreta" and b"segreta" not in client.get(reverse("ai:voce_lista")).content
    r = client.post(reverse("ai:voce_nuovo"), {"nome": "Cart", "tipo": "cartesia", "attivo": "on", "nuova_chiave": "k"})
    assert r.status_code == 200 and ServizioVoce.objects.count() == 1           # Cartesia senza voci
