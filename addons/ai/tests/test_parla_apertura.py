"""L'apertura di «Parla con Ada»: la frase con cui Ada accoglie chi si collega. La compone il server dai dati (mai il
modello), una cosa sola per volta e mai due volte la stessa nella giornata."""
import datetime

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.urls import reverse
from django.utils import timezone

from ai import apertura, parla, voce
from ai.models import Apertura, Conversazione, MessaggioChat, Proposta, ServizioVoce, Turno
from ai.strumenti import richiesta
from core.models import Azienda

pytestmark = pytest.mark.skipif("calendario" not in settings.ADDONS_ATTIVI, reason="serve l'app calendario")


def _alle(ora, minuto=0):
    return timezone.localtime().replace(hour=ora, minute=minuto, second=0, microsecond=0)


@pytest.fixture
def s(db, client, monkeypatch, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    a = Azienda.objects.first()
    u = User.objects.create_user("anna", password="x", first_name="Anna")
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    u.user_permissions.add(Permission.objects.get(content_type__app_label="calendario", codename="view_evento"))
    u.profilo.aziende.set([a])
    u.profilo.azienda_predefinita = a
    u.profilo.save()
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    valori = {"ai.voce": True, "ai.voce_cloud": False, "ai.url_voce": "http://speaches:8000", "ai.voce_telefono": True,
              "ai.modello_trascrizione": "Systran/faster-whisper-small", "ai.app_riservate": ""}
    originale = voce.parametri.leggi
    monkeypatch.setattr(voce.parametri, "leggi", lambda chiave, azienda=None: valori[chiave] if chiave in valori else originale(chiave, azienda))
    ServizioVoce.objects.create(nome="Kokoro", tipo="kokoro")
    return {"u": u, "az": a, "valori": valori, "richiesta": richiesta.nuova(u, a)}


def _evento(s, titolo, ora, minuto=0):
    from calendario.models import Evento
    inizio = _alle(ora, minuto)
    return Evento.objects.create(azienda=s["az"], titolo=titolo, inizio=inizio, fine=inizio + datetime.timedelta(hours=1),
                                 organizzatore=s["u"])


def _detta(s, ora, minuto=0):
    """Compone l'apertura a quell'ora e la segna come detta (l'utente ha toccato e l'ha sentita)."""
    ap = apertura.componi(s["richiesta"], _alle(ora, minuto))
    if ap is not None:
        apertura.segna_detta(ap, _alle(ora, minuto))
    return ap


def _chat_a_voce(s, titolo, ora, turni=2, generato=True, **campi):
    c = Conversazione.objects.create(utente=s["u"], titolo=titolo, titolo_generato=generato, **campi)
    for n in range(turni):
        t = Turno.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], voce=True, stato=Turno.COMPLETATO)
        Turno.objects.filter(pk=t.pk).update(iniziato=_alle(ora, n))
    return c


# ---------- la prima volta nella giornata ----------

def test_la_prima_volta_del_giorno_saluta_e_offre_l_agenda(s):
    _evento(s, "Riunione con Rossi", 10)
    _evento(s, "Demo", 15)
    _evento(s, "Call", 17)
    ap = apertura.componi(s["richiesta"], _alle(9))
    assert ap.tipo == Apertura.GIORNO and ap.detta is None
    assert ap.testo == ("Buongiorno Anna. Oggi hai 3 appuntamenti, il primo alle 10:00: «Riunione con Rossi». "
                        "Vuoi sapere cosa hai in agenda per oggi?")


def test_chi_e_gia_stato_qui_viene_riconosciuto(s):
    ieri = _chat_a_voce(s, "Ieri", 9)
    Turno.objects.filter(conversazione=ieri).update(iniziato=_alle(9) - datetime.timedelta(days=1))
    assert apertura.componi(s["richiesta"], _alle(9)).testo.startswith("Buongiorno Anna, ")
    assert "Buongiorno Anna, bentornat" not in Apertura.objects.get().testo          # niente parole col genere


def test_un_solo_appuntamento_lo_dice_senza_offrire_l_agenda(s):
    _evento(s, "Riunione con Rossi", 10, 30)
    assert apertura.componi(s["richiesta"], _alle(9)).testo == (
        "Buongiorno Anna. Oggi hai un appuntamento alle 10:30: «Riunione con Rossi». Come posso aiutarti?")


def test_nel_pomeriggio_conta_solo_quelli_che_restano(s):
    _evento(s, "Riunione con Rossi", 10)
    _evento(s, "Demo", 15)
    _evento(s, "Call", 17)
    assert apertura.componi(s["richiesta"], _alle(14)).testo == (
        "Buon pomeriggio Anna. Oggi ti restano 2 appuntamenti, il prossimo alle 15:00: «Demo». "
        "Vuoi sapere cosa hai in agenda per oggi?")
    Apertura.objects.all().delete()
    assert apertura.componi(s["richiesta"], _alle(19)).testo == "Buonasera Anna. Come posso aiutarti?"


def test_senza_appuntamenti_propone_le_notifiche_non_lette(s):
    from discuss.models import Notifica
    s["u"].user_permissions.add(Permission.objects.get(codename="view_canale"))
    s["richiesta"].user = User.objects.get(pk=s["u"].pk)
    for titolo in ("Mario ti ha scritto", "Nuova menzione"):
        Notifica.objects.create(utente=s["u"], tipo=Notifica.DIRETTO, titolo=titolo, url="/discuss/")
    assert apertura.componi(s["richiesta"], _alle(9)).testo == "Buongiorno Anna. Hai 2 notifiche non lette: vuoi sentirle?"


def test_senza_niente_da_dire_resta_il_saluto(s):
    assert apertura.componi(s["richiesta"], _alle(9)).testo == "Buongiorno Anna. Come posso aiutarti?"


def test_il_calendario_riservato_non_entra_nell_apertura(s):
    """L'apertura va al servizio di lettura e, come nota, al modello: i dati di un'app riservata non ci entrano."""
    _evento(s, "Colloquio con Bianchi", 10)
    _evento(s, "Demo", 15)
    s["valori"]["ai.app_riservate"] = "calendario"
    assert apertura.componi(s["richiesta"], _alle(9)).testo == "Buongiorno Anna. Come posso aiutarti?"


def test_chi_non_vede_il_calendario_non_sente_l_agenda(s):
    _evento(s, "Riunione con Rossi", 10)
    _evento(s, "Demo", 15)
    s["u"].user_permissions.remove(Permission.objects.get(content_type__app_label="calendario", codename="view_evento"))
    s["richiesta"].user = User.objects.get(pk=s["u"].pk)
    assert apertura.componi(s["richiesta"], _alle(9)).testo == "Buongiorno Anna. Come posso aiutarti?"


# ---------- non ripetersi ----------

def test_dopo_pochi_minuti_ada_non_dice_nulla(s):
    _evento(s, "Demo", 15)
    assert _detta(s, 9).tipo == Apertura.GIORNO
    c = Conversazione.objects.create(utente=s["u"], titolo="Preventivo")
    Proposta.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], strumento="crea_record", argomenti={}, titolo="Crea preventivo")
    assert apertura.componi(s["richiesta"], _alle(9, 5)) is None          # avrebbe da dire, ma è passato troppo poco
    assert _detta(s, 9, 20).tipo == Apertura.SOSPESO
    assert apertura.componi(s["richiesta"], _alle(11)) is None           # più tardi, ma niente di nuovo da dire
    assert Apertura.objects.count() == 2


def test_un_apertura_mai_sentita_si_ripropone(s):
    """Pagina aperta e richiusa senza toccare: Ada non ha parlato, quindi il saluto del giorno non è consumato."""
    prima = apertura.componi(s["richiesta"], _alle(9))
    dopo = apertura.componi(s["richiesta"], _alle(11))
    assert dopo.tipo == Apertura.GIORNO and dopo.pk != prima.pk and Apertura.objects.count() == 1


def test_ha_appena_parlato_a_voce_niente_apertura(s):
    _chat_a_voce(s, "Fatture", 9)                                        # due turni a voce alle 9:00 e 9:01
    assert apertura.componi(s["richiesta"], _alle(9, 6)) is None


# ---------- tornando dopo un po' ----------

def test_tornando_ricorda_l_appuntamento_vicino_una_volta_sola(s):
    _evento(s, "Demo", 15)
    _evento(s, "Call", 17)
    _detta(s, 9)
    ap = _detta(s, 14, 40)
    assert ap.tipo == Apertura.APPUNTAMENTO and ap.testo == "Rieccoti, Anna. Tra 20 minuti, alle 15:00, hai «Demo»."
    assert apertura.componi(s["richiesta"], _alle(14, 55)) is None        # lo stesso appuntamento non si ripete
    assert _detta(s, 16).testo == "Eccoti di nuovo, Anna. Tra un'ora, alle 17:00, hai «Call»."


def test_l_appuntamento_gia_detto_nel_saluto_non_si_ripete(s):
    _evento(s, "Demo", 15)
    assert "alle 15:00: «Demo»" in _detta(s, 14, 30).testo                # il saluto del giorno, mezz'ora prima
    assert apertura.componi(s["richiesta"], _alle(14, 45)) is None


def test_tornando_ricorda_la_modifica_in_sospeso(s):
    _detta(s, 9)
    c = Conversazione.objects.create(utente=s["u"], titolo="Preventivo")
    Proposta.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], strumento="crea_record", argomenti={},
                            titolo="Crea preventivo per Bianchi")
    ap = _detta(s, 11)
    assert ap.tipo == Apertura.SOSPESO and ap.conversazione == c
    assert ap.testo == ("Rieccoti, Anna. È rimasta in sospeso una modifica: «Crea preventivo per Bianchi». "
                        "Aspetta la tua conferma nella chat.")
    assert apertura.componi(s["richiesta"], _alle(13)) is None            # una volta per modifica


def test_un_titolo_che_ha_gia_le_virgolette_non_le_prende_due_volte(s):
    _detta(s, 9)
    c = Conversazione.objects.create(utente=s["u"], titolo="Appuntamento")
    Proposta.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], strumento="crea_record", argomenti={},
                            titolo="Crea evento «Appuntamento con Serafini»")
    assert _detta(s, 11).testo == ("Rieccoti, Anna. È rimasta in sospeso una modifica: Crea evento «Appuntamento con Serafini». "
                                   "Aspetta la tua conferma nella chat.")


def test_tornando_propone_di_riprendere_la_conversazione(s):
    _detta(s, 9)
    c = _chat_a_voce(s, "Fatture scadute di ottobre", 10)
    ap = _detta(s, 12)
    assert ap.tipo == Apertura.RIPRENDI and ap.conversazione == c
    assert ap.testo == "Rieccoti, Anna. Prima parlavamo di «Fatture scadute di ottobre»: riprendiamo da lì?"
    assert apertura.componi(s["richiesta"], _alle(14)) is None            # una volta per conversazione


def test_senza_un_titolo_vero_la_ripresa_non_lo_cita(s):
    _detta(s, 9)
    _chat_a_voce(s, "ciao ada", 10, generato=False)
    assert _detta(s, 12).testo == "Rieccoti, Anna. Vuoi riprendere la conversazione di prima?"


def test_non_si_riprende_una_domanda_sola_ne_una_chat_riservata(s):
    _detta(s, 9)
    _chat_a_voce(s, "Una domanda", 10, turni=1)
    _chat_a_voce(s, "Stipendi", 10, riservata=True)
    assert apertura.componi(s["richiesta"], _alle(12)) is None


def test_si_e_no(s):
    for testo in ("Sì", "sì, riprendiamo", "Si grazie", "ok va bene", "Certo", "d'accordo", "Va bene dai", "riprendiamo"):
        assert apertura.accetta(testo), testo
    for testo in ("No", "no grazie", "sinceramente no", "che appuntamenti ho oggi", "", "okra"):
        assert not apertura.accetta(testo), testo


# ---------- la pagina ----------

@pytest.fixture
def alle_nove(monkeypatch):
    ora = {"adesso": _alle(9)}
    monkeypatch.setattr(apertura, "_ora", lambda: ora["adesso"])
    return ora


def test_la_pagina_mostra_l_apertura_e_la_fa_dire_al_primo_tocco(client, s, alle_nove):
    _evento(s, "Riunione con Rossi", 10)
    _evento(s, "Demo", 15)
    html = client.get(reverse("ai:parla")).content.decode()
    ap = Apertura.objects.get()
    assert "Oggi hai 2 appuntamenti, il primo alle 10:00: «Riunione con Rossi»." in html
    assert "Vuoi sapere cosa hai in agenda per oggi?" in html and "cosa posso fare per te?" not in html
    assert f'data-apertura="{ap.pk}"' in html and reverse("ai:parla_apertura", args=[ap.pk]) in html
    assert reverse("ai:parla_apertura_detta", args=[ap.pk]) in html and "Tocca per iniziare" in html


def test_dentro_una_conversazione_o_in_un_app_niente_apertura(client, s, alle_nove):
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    assert 'data-apertura=""' in client.get(reverse("ai:parla_conversazione", args=[c.pk])).content.decode()
    s["u"].user_permissions.add(Permission.objects.get(codename="view_contatto"))
    html = client.get(reverse("ai:parla") + "?app=contatti").content.decode()
    assert 'data-apertura=""' in html and "cosa posso fare per te?" in html and not Apertura.objects.exists()


def test_tornando_subito_la_pagina_non_saluta_di_nuovo(client, s, alle_nove):
    apertura.segna_detta(apertura.componi(s["richiesta"], _alle(9)), _alle(9))
    alle_nove["adesso"] = _alle(9, 4)
    html = client.get(reverse("ai:parla")).content.decode()
    assert 'data-apertura=""' in html and "Dimmi pure, Anna." in html and "Buongiorno" not in html
    assert "cosa posso fare per te?" not in html and "Tocca e parla" in html


def test_da_capo_ricomincia_la_giornata(client, s, alle_nove):
    """Per le demo: /ai/parla/?da_capo=1 dimentica le aperture già dette e saluta come la prima volta."""
    apertura.segna_detta(apertura.componi(s["richiesta"], _alle(9)), _alle(9))
    alle_nove["adesso"] = _alle(9, 4)
    assert "Buongiorno Anna" in client.get(reverse("ai:parla") + "?da_capo=1").content.decode()


def test_voce_spenta_niente_apertura(client, s, alle_nove):
    s["valori"]["ai.voce"] = False
    client.get(reverse("ai:parla"))
    assert not Apertura.objects.exists()


def test_l_audio_legge_solo_il_testo_dell_apertura(client, s, alle_nove, monkeypatch):
    letti = []
    monkeypatch.setattr(parla.voce, "audio_di", lambda servizio, testo, lingua: letti.append((testo, lingua)) or (b"RIFF", "audio/wav"))
    _evento(s, "Demo", 15, 30)
    ap = apertura.componi(s["richiesta"], _alle(9))
    r = client.get(reverse("ai:parla_apertura", args=[ap.pk]))
    assert r.status_code == 200 and r["Content-Type"] == "audio/wav"
    assert letti == [("Buongiorno Anna. Oggi hai un appuntamento alle 15 e 30: «Demo». Come posso aiutarti?", "it")]
    assert Apertura.objects.get().detta is None                           # scaricarla non è averla sentita
    altro = User.objects.create_user("bruno", password="x")
    sua = Apertura.objects.create(utente=altro, azienda=s["az"], tipo=Apertura.GIORNO, testo="Segreto.")
    assert client.get(reverse("ai:parla_apertura", args=[sua.pk])).status_code == 404
    assert client.post(reverse("ai:parla_apertura_detta", args=[sua.pk])).status_code == 404


def test_detta_al_primo_tocco(client, s, alle_nove):
    ap = apertura.componi(s["richiesta"], _alle(9))
    assert client.get(reverse("ai:parla_apertura_detta", args=[ap.pk])).status_code == 405
    assert client.post(reverse("ai:parla_apertura_detta", args=[ap.pk])).status_code == 204
    assert Apertura.objects.get().detta == _alle(9)


# ---------- la risposta all'apertura ----------

@pytest.fixture
def note(monkeypatch):
    raccolte = []
    monkeypatch.setattr(parla.motore, "avvia", lambda c, t, u, a=None, **o: raccolte.append(o["nota"]) or Turno.objects.create(conversazione=c, utente=u, voce=True))
    return raccolte


def test_il_si_all_apertura_arriva_al_modello_con_quello_che_ada_ha_detto(client, s, alle_nove, note):
    _evento(s, "Riunione con Rossi", 10)
    _evento(s, "Demo", 15)
    ap = apertura.componi(s["richiesta"], _alle(9))
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Sì", "apertura": ap.pk}).json()
    assert "Hai aperto tu la conversazione dicendo all'utente: «Buongiorno Anna. Oggi hai 2 appuntamenti" in note[0]
    assert "non salutare di nuovo" in note[0] and "inizio della conversazione" not in note[0]
    assert Apertura.objects.get().detta == _alle(9)                       # con la voce spenta la segna la risposta
    assert Conversazione.objects.get(pk=r["conversazione"]).titolo == "Agenda di oggi"
    client.post(reverse("ai:parla_chiedi"), {"testo": "E domani?", "conversazione": r["conversazione"], "apertura": ap.pk})
    assert "Hai aperto tu" not in note[1]                                 # solo al primo turno


def test_una_domanda_dopo_l_apertura_resta_una_domanda(client, s, alle_nove, note):
    ap = apertura.componi(s["richiesta"], _alle(9))
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Quante fatture ho?", "apertura": ap.pk}).json()
    assert Conversazione.objects.get(pk=r["conversazione"]).titolo == "Quante fatture ho?" and "Hai aperto tu" in note[0]


def test_l_apertura_di_un_altro_non_conta(client, s, alle_nove, note):
    altro = User.objects.create_user("bruno", password="x")
    sua = Apertura.objects.create(utente=altro, azienda=s["az"], tipo=Apertura.GIORNO, testo="Segreto.")
    client.post(reverse("ai:parla_chiedi"), {"testo": "Ciao Ada", "apertura": sua.pk})
    assert "Segreto" not in note[0] and "inizio della conversazione" in note[0]


def test_dicendo_di_si_si_riprende_la_conversazione_di_prima(client, s, alle_nove, note):
    _detta(s, 8)
    c = _chat_a_voce(s, "Fatture scadute di ottobre", 8, 30)
    alle_nove["adesso"] = _alle(11)
    ap = apertura.componi(s["richiesta"], _alle(11))
    assert ap.tipo == Apertura.RIPRENDI
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Sì, riprendiamo", "apertura": ap.pk}).json()
    assert r["conversazione"] == c.pk and r["parla"] == reverse("ai:parla_conversazione", args=[c.pk])
    assert Conversazione.objects.filter(utente=s["u"]).count() == 1
    assert "Ha scelto di riprendere questa conversazione" in note[0] and "Oggi a voce avete già parlato" not in note[0]


def test_dicendo_altro_parte_una_conversazione_nuova(client, s, alle_nove, note):
    _detta(s, 8)
    c = _chat_a_voce(s, "Fatture scadute di ottobre", 8, 30)
    alle_nove["adesso"] = _alle(11)
    ap = apertura.componi(s["richiesta"], _alle(11))
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "No, dimmi gli ordini di oggi", "apertura": ap.pk}).json()
    assert r["conversazione"] != c.pk and "Ha scelto di riprendere" not in note[0]


def test_la_modifica_in_sospeso_a_voce_non_si_conferma(client, s, alle_nove, note):
    """La conferma resta un bottone nella chat: il modello non deve far credere di averla eseguita."""
    _detta(s, 8)
    c = Conversazione.objects.create(utente=s["u"], titolo="Preventivo Bianchi")
    Proposta.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], strumento="crea_record", argomenti={}, titolo="Crea preventivo")
    alle_nove["adesso"] = _alle(11)
    html = client.get(reverse("ai:parla")).content.decode()
    assert "È rimasta in sospeso una modifica: «Crea preventivo»." in html
    assert f'data-chat="{reverse("ai:conversazione", args=[c.pk])}"' in html      # «Chiudi» porta alla chat della modifica
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Sì, confermala", "apertura": Apertura.objects.first().pk}).json()
    assert r["conversazione"] != c.pk
    assert "non puoi confermarla né eseguirla" in note[0] and "nella conversazione «Preventivo Bianchi»" in note[0]


# ---------- la memoria della giornata ----------

def test_una_conversazione_nuova_sa_di_cosa_si_e_parlato_oggi(client, s, alle_nove, note):
    c = _chat_a_voce(s, "Fatture scadute di ottobre", 8)
    MessaggioChat.objects.create(conversazione=c, ruolo=MessaggioChat.UTENTE, testo="Quante fatture scadute ho?")
    MessaggioChat.objects.create(conversazione=c, ruolo=MessaggioChat.ASSISTENTE, testo="Ne hai 12, per 4.300 €.")
    riservata = _chat_a_voce(s, "Stipendi di Mario", 8, riservata=True)
    MessaggioChat.objects.create(conversazione=riservata, ruolo=MessaggioChat.UTENTE, testo="Quanto prende Mario?")
    ieri = _chat_a_voce(s, "Cose di ieri", 8)
    Turno.objects.filter(conversazione=ieri).update(iniziato=_alle(8) - datetime.timedelta(days=1))
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "Come dicevamo prima, quali sono le più vecchie?"}).json()
    assert "Oggi a voce avete già parlato di:" in note[0]
    assert "«Fatture scadute di ottobre»" in note[0] and "«Quante fatture scadute ho?»" in note[0] and "Ne hai 12, per 4.300 €." in note[0]
    assert "Stipendi" not in note[0] and "Mario" not in note[0] and "Cose di ieri" not in note[0]
    client.post(reverse("ai:parla_chiedi"), {"testo": "E poi?", "conversazione": r["conversazione"]})
    assert "Oggi a voce avete già parlato" not in note[1]                 # solo al primo turno
