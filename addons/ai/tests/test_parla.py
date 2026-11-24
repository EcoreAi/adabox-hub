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
    monkeypatch.setattr(parla.voce, "trascrivi", lambda f, lingua="", azienda=None, parole=(), **_: lingue.append((lingua, parole)) or "  quante   fatture  ")
    r = client.post(reverse("ai:parla_ascolta"), {"audio": SimpleUploadedFile("v.webm", b"x", content_type="audio/webm")})
    assert r.json() == {"testo": "quante fatture"} and lingue[0][0] == "it" and lingue[0][1][0] == "Ada"


def test_chiedi_avvia_il_turno_con_la_nota_della_voce(client, s, monkeypatch):
    chiamate = []

    def avvia(conversazione, testo, utente, azienda=None, **opzioni):
        chiamate.append((testo, opzioni))
        return Turno.objects.create(conversazione=conversazione, utente=utente, stato=Turno.COMPLETATO)
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
    assert r.status_code == 200 and letti == [parla.FRASI["calendario"][0]]
    assert client.get(reverse("ai:parla_frase", args=["calendario-2"])).status_code == 200 and letti[-1] == parla.FRASI["calendario"][2]
    for chiave in ["qualsiasi-testo", "calendario-9", "calendario-x", "attimo-"]:
        assert client.get(reverse("ai:parla_frase", args=[chiave])).status_code == 404
    html = client.get(reverse("ai:parla")).content.decode()
    assert 'id="pa-frasi"' in html and "calendario_agenda" in html and '"varianti"' in html


def test_saluto_solo_al_primo_turno(client, s, monkeypatch):
    note = []
    monkeypatch.setattr(parla.motore, "avvia", lambda c, t, u, a=None, **o: note.append(o["nota"]) or Turno.objects.create(conversazione=c, utente=u, stato=Turno.COMPLETATO))
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Ciao Ada"}).json()
    assert "come posso aiutarti?»" in note[0] and "inizio della conversazione" in note[0]
    client.post(reverse("ai:parla_chiedi"), {"testo": "Che appuntamenti ho?", "conversazione": r["conversazione"]})
    assert "non salutare di nuovo" in note[1] and "inizio della conversazione" not in note[1]


def test_parla_con_ada_nella_testata_di_ogni_app(client, s):
    html = client.get(reverse("core:profilo")).content.decode()
    assert 'class="ai-parla-testata"' in html and f'href="{reverse("ai:parla")}"' in html
    s["valori"]["ai.voce"] = False                                               # voce spenta: niente icona
    assert 'ai-parla-testata' not in client.get(reverse("core:profilo")).content.decode()


def test_pagina_con_le_app_e_le_notifiche(client, s):
    """In alto: l'elenco delle app a cui limitarsi e la campanella con le notifiche non lette."""
    from discuss.models import Notifica
    s["u"].user_permissions.add(*Permission.objects.filter(codename__in=["view_contatto", "view_canale"]))
    client.force_login(User.objects.get(pk=s["u"].pk))
    Notifica.objects.create(utente=s["u"], tipo=Notifica.DIRETTO, titolo="Mario ti ha scritto", url="/discuss/")
    Notifica.objects.create(utente=s["u"], tipo=Notifica.DIRETTO, titolo="Già letta", url="/discuss/", letta=True)
    html = client.get(reverse("ai:parla") + "?app=contatti").content.decode()
    assert 'data-pa-app="contatti"' in html and 'data-ambito="contatti"' in html
    assert 'data-pa-notifiche' in html and '>1<' in html
    assert "cosa posso fare per te?" in html


def test_chiedi_limitata_a_un_app(client, s, monkeypatch):
    s["u"].user_permissions.add(*Permission.objects.filter(codename="view_contatto"))
    client.force_login(User.objects.get(pk=s["u"].pk))
    monkeypatch.setattr(parla.motore, "avvia", lambda c, t, u, a=None, **o: Turno.objects.create(conversazione=c, utente=u))
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Chi sono i clienti?", "app": "contatti"}).json()
    assert Conversazione.objects.get(pk=r["conversazione"]).ambito == "contatti"
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Altro", "app": "inventata"}).json()
    assert Conversazione.objects.get(pk=r["conversazione"]).ambito == ""


def test_a_voce_ada_legge_le_notifiche():
    assert "notifiche_leggi" in parla.STRUMENTI_VOCE


def test_pulsante_senza_voce(client, s):
    """Per la riservatezza si può spegnere la voce di Ada: risponde solo con i sottotitoli."""
    html = client.get(reverse("ai:parla")).content.decode()
    assert "data-pa-muto" in html and 'aria-pressed="false"' in html


# ---------- una domanda nuova mentre la risposta di prima è ancora in corso ----------

@pytest.fixture
def motore_finto(s, monkeypatch):
    """Il motore vero con un modello finto: serve a vedere che cosa fa `motore.avvia` con un turno ancora in corso."""
    from decimal import Decimal

    from ai.gateway import esecuzione
    from ai.models import AnelloCatena, Modello, Profilo, Provider
    monkeypatch.setattr(esecuzione, "_dormi", lambda secondi: None)
    modello = Modello.objects.create(provider=Provider.objects.create(nome="Finto", tipo="finto", locale=True), id_api="finto-1",
                                     etichetta="Finto", prezzo_input=Decimal(1), prezzo_output=Decimal(1))
    for compito in ("chat", "titoli"):
        AnelloCatena.objects.create(profilo=Profilo.objects.create(nome=compito, compito=compito), modello=modello, ordine=1)
    return s


def _in_corso(s, **campi):
    c = Conversazione.objects.create(utente=s["u"], titolo="Fatture")
    return c, Turno.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], **campi)


def test_la_domanda_dopo_un_interruzione_non_va_persa(client, motore_finto, monkeypatch):
    """Ada pensa (uno strumento lavora), l'utente la interrompe e chiede altro: lo stop non è ancora stato visto dal
    turno. Prima `motore.avvia` restituiva il turno vecchio: la domanda spariva e la pagina rileggeva la risposta di prima."""
    from ai.gateway import finto
    from ai.motore import turni
    c, vecchio = _in_corso(motore_finto, voce=True)

    def il_turno_vede_lo_stop(secondi):                       # come fa il motore al primo controllo dopo lo stop
        assert Turno.objects.get(pk=vecchio.pk).richiesta_stop
        Turno.objects.filter(pk=vecchio.pk).update(stato=Turno.FERMATO)
    monkeypatch.setattr(turni.time, "sleep", il_turno_vede_lo_stop)
    with finto.con_copione([["Sono tre."]]):
        r = client.post(reverse("ai:parla_chiedi"), {"testo": "E quelle scadute?", "conversazione": c.pk})
    assert r.status_code == 200 and r.json()["turno"] != vecchio.pk
    assert list(c.messaggi.values_list("ruolo", "testo")) == [("utente", "E quelle scadute?"), ("assistente", "Sono tre.")]


def test_se_il_turno_di_prima_non_si_chiude_la_pagina_lo_dice(client, motore_finto, monkeypatch):
    from ai.motore import turni
    c, vecchio = _in_corso(motore_finto, voce=True)
    monkeypatch.setattr(turni, "ATTESA_STOP", 0)
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "E quelle scadute?", "conversazione": c.pk})
    assert r.status_code == 409 and "riprova" in r.json()["errore"]
    assert Turno.objects.get(pk=vecchio.pk).richiesta_stop and not c.messaggi.exists()


def test_una_risposta_avviata_dalla_chat_scritta_non_si_ferma_a_voce(client, motore_finto):
    c, ricerca = _in_corso(motore_finto, compito="ricerca")
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Che ore sono?", "conversazione": c.pk})
    assert r.status_code == 409 and "già una risposta in corso" in r.json()["errore"]
    ricerca.refresh_from_db()
    assert ricerca.stato == Turno.IN_CORSO and not ricerca.richiesta_stop and not c.messaggi.exists()


# ---------- chat riservata: nemmeno la voce di chi parla esce dal server ----------

def test_in_una_chat_riservata_si_trascrive_solo_in_locale(client, s, monkeypatch):
    visti = []
    monkeypatch.setattr(parla.voce, "trascrivi", lambda f, lingua="", **o: visti.append(o["solo_locale"]) or "ciao")
    riservata = Conversazione.objects.create(utente=s["u"], titolo="Stipendi", riservata=True)
    normale = Conversazione.objects.create(utente=s["u"], titolo="Fatture")
    altrui = Conversazione.objects.create(utente=User.objects.create_user("bruno", password="x"), titolo="Sua", riservata=True)

    def audio():
        return SimpleUploadedFile("v.webm", b"x", content_type="audio/webm")
    for url in (reverse("ai:parla_ascolta"), reverse("ai:trascrivi_voce")):       # a voce e con la dettatura della chat
        visti.clear()
        client.post(url, {"audio": audio(), "conversazione": riservata.pk})
        client.post(url, {"audio": audio(), "conversazione": normale.pk})
        client.post(url, {"audio": audio()})
        client.post(url, {"audio": audio(), "conversazione": altrui.pk})
        assert visti == [True, False, False, False], url
