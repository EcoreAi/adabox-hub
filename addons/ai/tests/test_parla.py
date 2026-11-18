"""«Parla con Ada»: la conversazione a voce. Il browser trascrive, chiede e fa leggere un tratto alla volta della
risposta del turno; il server legge solo il testo del turno, mai un testo mandato dal browser."""
import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ai import parla, voce
from ai.models import Conversazione, ServizioVoce, Turno
from core.models import Azienda


@pytest.fixture
def s(db, client, monkeypatch, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    a = Azienda.objects.first()
    u = User.objects.create_user("anna", password="x")
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    u.profilo.aziende.set([a])
    u.profilo.azienda_predefinita = a
    u.profilo.save()
    client.force_login(User.objects.get(pk=u.pk))
    valori = {"ai.voce": True, "ai.voce_cloud": False, "ai.url_voce": "http://speaches:8000",
              "ai.modello_trascrizione": "Systran/faster-whisper-small", "ai.voce_telefono": True,
              "ai.voce_silenzio": "1.0", "ai.voce_ascolto_dopo": "20"}
    originale = voce.parametri.leggi
    monkeypatch.setattr(voce.parametri, "leggi", lambda chiave, azienda=None: valori[chiave] if chiave in valori else originale(chiave, azienda))
    ServizioVoce.objects.create(nome="Kokoro", tipo="kokoro")
    return {"u": User.objects.get(pk=u.pk), "az": a, "valori": valori}


def test_pagina_accesa_e_spenta(client, s):
    html = client.get(reverse("ai:parla")).content.decode()
    assert "data-parla" in html and "ai/parla.js" in html and 'data-silenzio="1000"' in html
    assert 'data-ascolto-dopo="15000"' in html                       # oltre il massimo: 15 secondi
    s["valori"]["ai.voce"] = False
    html = client.get(reverse("ai:parla")).content.decode()
    assert "La voce non è attiva" in html and "ai/parla.js" not in html


def test_senza_permesso_niente_pagina(client, s):
    s["u"].user_permissions.remove(Permission.objects.get(codename="add_conversazione"))
    client.force_login(User.objects.get(pk=s["u"].pk))
    assert client.get(reverse("ai:parla")).status_code == 403


def test_conversazione_di_un_altro_non_si_apre(client, s):
    altro = User.objects.create_user("bruno", password="x")
    sua = Conversazione.objects.create(utente=altro, titolo="Sua")
    assert client.get(reverse("ai:parla_conversazione", args=[sua.pk])).status_code == 404


def test_ascolta_trascrive_in_italiano(client, s, monkeypatch):
    lingue = []
    monkeypatch.setattr(parla.voce, "trascrivi", lambda f, lingua="", azienda=None, parole=(): lingue.append((lingua, parole)) or "  quante   fatture  ")
    r = client.post(reverse("ai:parla_ascolta"), {"audio": SimpleUploadedFile("v.webm", b"x", content_type="audio/webm")})
    assert r.json() == {"testo": "quante fatture"} and lingue[0][0] == "it" and lingue[0][1][0] == "Ada"


def test_chiedi_avvia_il_turno_con_la_nota_della_voce(client, s, monkeypatch):
    chiamate = []

    def avvia(conversazione, testo, utente, azienda=None, **opzioni):
        chiamate.append((testo, opzioni))
        return Turno.objects.create(conversazione=conversazione, utente=utente)
    monkeypatch.setattr(parla.motore, "avvia", avvia)
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Quante fatture  ho?"}).json()
    c = Conversazione.objects.get(pk=r["conversazione"])
    assert c.utente == s["u"] and c.titolo == "Quante fatture ho?"
    assert r["flusso"] == reverse("ai:flusso", args=[r["turno"]]) and r["parla"] == reverse("ai:parla_conversazione", args=[c.pk])
    testo, opzioni = chiamate[0]
    assert testo == "Quante fatture ho?" and opzioni["web"] is False and opzioni["voce"] is True
    assert "L'utente si chiama anna" in opzioni["nota"] and "telefonata" in opzioni["nota"]
    # stessa conversazione, dopo un'interruzione: il modello sa fin dove l'utente ha sentito
    client.post(reverse("ai:parla_chiedi"), {"testo": "e quelle scadute?", "conversazione": c.pk, "sentito": "Hai dodici fatture"})
    assert Conversazione.objects.filter(utente=s["u"]).count() == 1
    assert "ha sentito solo fin qui: «Hai dodici fatture»" in chiamate[1][1]["nota"]
    assert client.post(reverse("ai:parla_chiedi"), {"testo": "  "}).status_code == 400


def test_audio_solo_dal_testo_del_turno(client, s, monkeypatch):
    letti = []
    monkeypatch.setattr(parla.voce, "audio_di", lambda servizio, testo, lingua: letti.append(testo) or (b"RIFF", "audio/wav"))
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    turno = Turno.objects.create(conversazione=c, utente=s["u"], testo="Hai dodici fatture. Tre sono scadute, per **mille euro**.")
    r = client.get(reverse("ai:parla_audio", args=[turno.pk, 0, 20]))
    assert r.status_code == 200 and r["Content-Type"] == "audio/wav" and letti == ["Hai dodici fatture."]
    client.get(reverse("ai:parla_audio", args=[turno.pk, 20, len(turno.testo)]))
    assert letti[-1] == "Tre sono scadute, per mille euro."                # niente asterischi nella voce
    assert client.get(reverse("ai:parla_audio", args=[turno.pk, 0, len(turno.testo) + 1])).status_code == 404
    assert client.get(reverse("ai:parla_audio", args=[turno.pk, 10, 10])).status_code == 404
    turno.testo = "x" * 1000
    turno.save()
    assert client.get(reverse("ai:parla_audio", args=[turno.pk, 0, parla.CARATTERI_PEZZO + 1])).status_code == 404
    altro = User.objects.create_user("bruno", password="x")
    suo = Turno.objects.create(conversazione=Conversazione.objects.create(utente=altro, titolo="y"), utente=altro, testo="Segreto.")
    assert client.get(reverse("ai:parla_audio", args=[suo.pk, 0, 8])).status_code == 404


def test_fine_del_flusso_porta_il_testo_completo(client, s):
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    turno = Turno.objects.create(conversazione=c, utente=s["u"], testo="Ecco tutto.", stato=Turno.COMPLETATO)
    corpo = "".join(p.decode() if isinstance(p, bytes) else p for p in client.get(reverse("ai:flusso", args=[turno.pk])).streaming_content)
    assert "event: fine" in corpo and '"testo": "Ecco tutto."' in corpo


def test_la_chat_sul_telefono_apre_parla_con_ada(client, s):
    html = client.get(reverse("ai:chat")).content.decode()
    assert "pointer: coarse" in html and reverse("ai:parla") in html and 'class="ai-parla-testata"' in html
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    html = client.get(reverse("ai:conversazione", args=[c.pk])).content.decode()
    assert "pointer: coarse" not in html                                         # dentro una chat non si salta via
    assert reverse("ai:parla_conversazione", args=[c.pk]) in html               # l'icona in testata tiene la conversazione
    s["valori"]["ai.voce_telefono"] = False
    assert "pointer: coarse" not in client.get(reverse("ai:chat")).content.decode()


def test_la_voce_non_cambia_lingua_a_meta_risposta(client, s, monkeypatch):
    lingue = []
    monkeypatch.setattr(parla.voce, "audio_di", lambda servizio, testo, lingua: lingue.append(lingua) or (b"RIFF", "audio/wav"))
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    testo = "Oggi hai sei appuntamenti in calendario. Ora, alle tredici e quindici, c'è la riunione commerciale."
    turno = Turno.objects.create(conversazione=c, utente=s["u"], testo=testo)
    client.get(reverse("ai:parla_audio", args=[turno.pk, 0, 40]))            # il caso visto: letto con la voce inglese
    client.get(reverse("ai:parla_audio", args=[turno.pk, 41, len(testo)]))
    assert lingue == ["it", "it"]


def test_frasi_d_attesa_solo_quelle_dell_elenco(client, s, monkeypatch):
    letti = []
    monkeypatch.setattr(parla.voce, "audio_di", lambda servizio, testo, lingua: letti.append(testo) or (b"RIFF", "audio/wav"))
    r = client.get(reverse("ai:parla_frase", args=["calendario"]))
    assert r.status_code == 200 and letti == ["Guardo il calendario."]
    assert client.get(reverse("ai:parla_frase", args=["qualsiasi-testo"])).status_code == 404
    html = client.get(reverse("ai:parla")).content.decode()
    assert 'id="pa-frasi"' in html and "calendario_agenda" in html


def test_parla_con_ada_nella_testata_di_ogni_app(client, s):
    html = client.get(reverse("core:profilo")).content.decode()
    assert 'class="ai-parla-testata"' in html and f'href="{reverse("ai:parla")}"' in html
    s["valori"]["ai.voce"] = False                                               # voce spenta: niente icona
    assert 'ai-parla-testata' not in client.get(reverse("core:profilo")).content.decode()
