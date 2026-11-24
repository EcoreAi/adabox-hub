"""I costi della voce cloud: ogni chiamata a un servizio con un prezzo entra nei Consumi (caratteri letti, secondi
trascritti); la quota della voce sta nella licenza e oltre non ferma nulla, si fattura il di più; avvisi vicino alla
quota e vicino a ciò che il piano del fornitore comprende; il riepilogo per il portale dice quanta parte è voce."""
import datetime
import json
from decimal import Decimal

import httpx2 as httpx
import pytest
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from ai import consumi_portale, licenza, limiti, voce
from ai.forms import ServizioVoceForm
from ai.models import Licenza, ServizioVoce, Turno
from core import cifratura
from core.models import Azienda
from core.registry import pacchetti

OGGI = timezone.localdate()


@pytest.fixture
def s(db, monkeypatch):
    cache.clear()
    azienda = Azienda.objects.first()
    anna = User.objects.create_user("anna", email="anna@example.com", password="x")
    valori = {"ai.voce": True, "ai.voce_cloud": True, "ai.trascrizione_cloud": True, "ai.url_voce": ""}
    originale = voce.parametri.leggi
    monkeypatch.setattr(voce.parametri, "leggi", lambda chiave, a=None: valori[chiave] if chiave in valori else originale(chiave, a))
    monkeypatch.setattr(voce, "sintetizza", lambda servizio, testo, lingua="it", http_client=None: (b"mp3", "audio/mpeg"))
    lettura = ServizioVoce.objects.create(nome="Cartesia", tipo=ServizioVoce.CARTESIA, voce_it="v", voce_en="v",
                                          chiave_cifrata=cifratura.cifra("k"), prezzo=Decimal("30"))
    yield {"az": azienda, "anna": anna, "lettura": lettura}
    cache.clear()


@pytest.fixture
def chiavi(settings, tmp_path):
    pem, pub = pacchetti.genera_chiavi()
    settings.MODULI_CHIAVI_FIDATE = [pub]
    settings.AI_LICENZA_SVILUPPO = False
    percorso = tmp_path / "privata.pem"
    percorso.write_bytes(pem)
    return percorso


def _licenza(chiavi, **dati):
    base = {"cliente": "Rossi Srl", "emessa": OGGI.isoformat(), "scadenza": (OGGI + datetime.timedelta(days=365)).isoformat(), "utenti": 0}
    Licenza.objects.create(testo=json.dumps(licenza.firma({**base, **dati}, pacchetti.carica_privata(chiavi))))


def _spesa_voce(s, dollari):
    Turno.objects.create(utente=s["anna"], azienda=s["az"], compito="voce_lettura", stato=Turno.COMPLETATO, costo=Decimal(dollari),
                         uso={"servizio": s["lettura"].pk, "caratteri": 0})


def test_ogni_lettura_nuova_entra_nei_consumi(s):
    testo = "Hai dodici fatture."                                    # 19 caratteri a 30 $ al milione
    voce.leggi(s["lettura"], testo, "it", s["anna"], s["az"])
    voce.leggi(s["lettura"], testo, "it", s["anna"], s["az"])        # dalla cache: il servizio non è chiamato, non costa
    riga = Turno.objects.get()
    assert (riga.compito, riga.stato, riga.conversazione_id, riga.utente, riga.azienda) == ("voce_lettura", "completato", None, s["anna"], s["az"])
    assert riga.uso == {"servizio": s["lettura"].pk, "nome": "Cartesia", "caratteri": 19, "chiamate": 1} and riga.costo == Decimal("0.000570")
    voce.leggi(s["lettura"], "Tre sono scadute.", "it", s["anna"], s["az"])
    riga.refresh_from_db()                                           # stessa persona, stesso giorno: la stessa riga
    assert Turno.objects.count() == 1 and riga.uso["caratteri"] == 36 and riga.uso["chiamate"] == 2
    assert limiti.spesa_mese(s["az"]) == riga.costo == Decimal("0.001080")      # conta nel tetto di spesa dell'azienda
    assert limiti.utenti_del_mese() == set()                          # non è un posto della licenza


def test_senza_prezzo_e_in_locale_non_si_segna_nulla(s):
    del_cliente = ServizioVoce.objects.create(nome="Suo", tipo=ServizioVoce.AZURE, regione="westeurope", chiave_cifrata=cifratura.cifra("k"))
    locale = ServizioVoce.objects.create(nome="Kokoro", tipo=ServizioVoce.KOKORO, prezzo=Decimal("30"))
    voce.leggi(del_cliente, "Ciao a tutti.", "it", s["anna"], s["az"])
    voce.leggi(locale, "Ciao a tutti.", "it", s["anna"], s["az"])
    assert not Turno.objects.exists()


def test_la_trascrizione_conta_i_secondi(s):
    mistral = ServizioVoce.objects.create(nome="Voxtral", tipo=ServizioVoce.MISTRAL, uso=ServizioVoce.TRASCRIZIONE,
                                          chiave_cifrata=cifratura.cifra("k"), prezzo=Decimal("0.006"))

    def client(risposta):
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=risposta)))

    def audio(byte=b"audio"):
        return SimpleUploadedFile("v.webm", byte, content_type="audio/webm")
    assert voce.trascrivi(audio(), "it", client({"text": "ciao", "usage": {"prompt_audio_seconds": 90}}), azienda=s["az"], utente=s["anna"]) == "ciao"
    riga = Turno.objects.get(compito="voce_trascrizione")
    assert riga.uso["secondi"] == 90 and riga.costo == Decimal("0.009000")          # un minuto e mezzo a 0,006 $ al minuto
    # il fornitore non dice la durata: una stima dalla dimensione (Opus, circa 32 kbit/s)
    voce.trascrivi(audio(b"x" * 40000), "it", client({"text": "ciao"}), azienda=s["az"], utente=s["anna"])
    riga.refresh_from_db()
    assert riga.uso["secondi"] == 100 and riga.uso["chiamate"] == 2
    assert limiti.uso_del_piano(mistral) == 2                         # in minuti, per eccesso


def test_la_quota_sta_nella_licenza_con_qualunque_formula(db, chiavi):
    _licenza(chiavi, quota_voce="25")                                 # chiave del cliente per i modelli, voce fornita da noi
    stato = licenza.attuale()
    assert stato.valida and stato.formula == licenza.PROPRIA and stato.quota_voce == Decimal("25")
    assert licenza.quota_voce({"quota_voce": "-3"}) == 0 and licenza.quota_voce({"quota_voce": "x"}) == 0 and licenza.quota_voce(None) == 0
    uscita = chiavi.parent / "licenza.json"
    call_command("ai_licenza", chiave=str(chiavi), cliente="Rossi", scadenza="2099-01-01", quota_voce="40", uscita=str(uscita))
    assert json.loads(uscita.read_text())["licenza"]["quota_voce"] == "40"


def test_vicino_alla_quota_si_avvisa_e_oltre_si_continua_segnando_il_di_piu(s, chiavi, client):
    _licenza(chiavi, quota_voce="10")
    admin = User.objects.create_user("admin", email="admin@example.com", password="x")
    admin.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    admin.profilo.aziende.set([s["az"]])

    def controlla():
        cache.clear()                                                 # il controllo degli avvisi è al massimo uno al minuto
        limiti.dopo_la_voce(s["lettura"])
    _spesa_voce(s, "7")
    controlla()
    assert limiti.voce() == (Decimal("7"), Decimal("10"), Decimal("0")) and limiti.avviso_voce() == "" and not mail.outbox
    _spesa_voce(s, "1.5")
    controlla()
    controlla()
    assert "usati 8.50 $ su 10 $" in limiti.avviso_voce()
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["admin@example.com"] and "8.50 $ su 10 $" in mail.outbox[0].subject
    _spesa_voce(s, "3")
    controlla()
    controlla()
    assert limiti.voce()[2] == Decimal("1.5") and "superata la quota" in limiti.avviso_voce() and "1.50 $" in limiti.avviso_voce()
    assert len(mail.outbox) == 2 and "superata la quota" in mail.outbox[1].subject
    # la voce non si ferma: si continua a leggere, e la chat e la pagina della licenza lo dicono
    assert voce.blocco(s["anna"], s["az"]) == ""
    voce.leggi(s["lettura"], "Ancora una frase.", "it", s["anna"], s["az"])
    client.force_login(User.objects.get(pk=admin.pk))
    assert "superata la quota mensile del piano" in client.get("/ai/chat/").content.decode()
    pagina = client.get("/ai/licenza/").content.decode()
    assert "Voce cloud del mese" in pagina and "oltre la quota" in pagina


def test_senza_quota_nella_licenza_nessun_avviso(s, chiavi):
    _licenza(chiavi)
    _spesa_voce(s, "500")
    cache.clear()
    limiti.dopo_la_voce(s["lettura"])
    assert limiti.voce() == (Decimal("500"), Decimal("0"), Decimal("0")) and limiti.avviso_voce() == "" and not mail.outbox


def test_il_global_admin_sa_quando_il_piano_del_fornitore_sta_finendo(s):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    User.objects.create_user("admin", email="admin@example.com", password="x")
    ServizioVoce.objects.filter(pk=s["lettura"].pk).update(compresi_nel_piano=1000)
    s["lettura"].refresh_from_db()
    voce.leggi(s["lettura"], "a" * 700, "it", s["anna"], s["az"])
    assert limiti.uso_del_piano(s["lettura"]) == 700 and not mail.outbox
    cache.delete(f"ai-voce-avvisi:{s['lettura'].pk}")
    voce.leggi(s["lettura"], "b" * 150, "it", s["anna"], s["az"])
    cache.delete(f"ai-voce-avvisi:{s['lettura'].pk}")
    voce.leggi(s["lettura"], "c" * 10, "it", s["anna"], s["az"])
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [capo.email] and "850 caratteri su 1000" in mail.outbox[0].subject


def test_il_riepilogo_per_il_portale_dice_quanta_parte_e_voce(s):
    Turno.objects.create(utente=s["anna"], azienda=s["az"], compito="chat", stato=Turno.COMPLETATO, costo=Decimal("2"), costo_fornito=Decimal("2"))
    _spesa_voce(s, "3")
    r = consumi_portale.riepilogo(OGGI.replace(day=1))
    assert (r["costo"], r["costo_fornito"], r["costo_voce"]) == ("5.000000", "2.000000", "3.000000")
    assert r["turni"] == 1 and r["utenti"] == 1                       # le righe della voce non sono turni


def test_con_la_chiave_del_cliente_al_portale_va_solo_la_voce(s, settings, monkeypatch):
    """Formula «propria» con la voce fornita da noi: il mese parte per la voce, senza quello che il cliente spende con
    la sua chiave per i modelli."""
    Turno.objects.create(utente=s["anna"], azienda=s["az"], compito="chat", stato=Turno.COMPLETATO, costo=Decimal("40"))
    settings.LICENZA_PORTALE_URL, settings.LICENZA_TOKEN = "https://portale.example/rivendita/api", "segreto"
    inviati = []
    monkeypatch.setattr(consumi_portale, "_chiama", inviati.append)
    assert consumi_portale.invia() is None                           # senza voce non riferisce nulla, come prima
    _spesa_voce(s, "3")
    assert consumi_portale.invia().startswith("inviati")
    mese = inviati[0]["mesi"][0]
    assert (mese["costo"], mese["costo_fornito"], mese["costo_voce"]) == ("3.000000", "0.000000", "3.000000")


def test_prezzo_e_piano_li_imposta_solo_il_global_admin(s):
    dati = {"nome": "Cartesia", "tipo": "cartesia", "uso": "lettura", "voce_it": "v", "voce_en": "v", "attivo": "on", "prezzo": "0"}
    assert "prezzo" not in ServizioVoceForm(instance=s["lettura"]).fields
    form = ServizioVoceForm(dati, instance=s["lettura"])              # chi amministra l'azienda non azzera il prezzo
    assert form.is_valid(), form.errors
    form.save()
    s["lettura"].refresh_from_db()
    assert s["lettura"].prezzo == Decimal("30")
    del_global_admin = type("Form", (ServizioVoceForm,), {"global_admin": True})
    form = del_global_admin({**dati, "prezzo": "45", "compresi_nel_piano": "500000"}, instance=s["lettura"])
    assert form.is_valid(), form.errors
    form.save()
    s["lettura"].refresh_from_db()
    assert (s["lettura"].prezzo, s["lettura"].compresi_nel_piano) == (Decimal("45"), 500000)
