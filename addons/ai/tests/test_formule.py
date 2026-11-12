"""Le formule con cui l'assistente si vende (ai.licenza): la quota sui provider forniti con il piano, chi può
toccarli, il costo che resta quando una chat si elimina e i consumi riferiti al portale."""
import datetime
import io
import json
import urllib.error
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core.management import CommandError, call_command
from django.utils import timezone

import ai
from ai import consumi_portale, licenza, limiti, motore
from ai.gateway import ErroreModello, esecuzione, finto
from ai.models import AnelloCatena, ChiaveAzienda, Conversazione, Evento, Licenza, Modello, Profilo, Provider, Turno
from ai.tests.test_licenza import _licenza, chiavi  # noqa: F401  (fixture)
from core import cifratura
from core import licenza as licenza_istanza
from core.models import Azienda
from core.registry import manifest
from core.registry.groups import crea_gruppi


def _modello(nome, gestito=False, prezzo="100"):
    provider = Provider.objects.create(nome=nome, tipo="finto", gestito=gestito)
    return Modello.objects.create(provider=provider, id_api=nome.lower(), etichetta=nome, prezzo_input=Decimal(prezzo),
                                  prezzo_output=Decimal(prezzo))


def _catena(*modelli, compito="chat"):
    profilo = Profilo.objects.create(nome=compito, compito=compito)
    for ordine, modello in enumerate(modelli, start=1):
        AnelloCatena.objects.create(profilo=profilo, modello=modello, ordine=ordine)
    return [(m, "") for m in modelli]


def _con_formula(chiavi, **termini):  # noqa: F811
    Licenza.objects.all().delete()
    Licenza.objects.create(testo=_licenza(chiavi, **termini))


@pytest.fixture
def amministratore(db, client):
    """L'Admin del cliente: tutti i permessi dell'assistente, ma non è il Global Admin."""
    crea_gruppi(manifest.leggi(Path(ai.__file__).parent))
    utente = User.objects.create_user("admin", "admin@example.com", "x")
    utente.groups.add(Group.objects.get(name="AI / Amministratore"))
    client.force_login(utente)
    return utente


# ---------- i termini nella licenza ----------

def test_termini_nella_licenza_dell_assistente(db, chiavi):  # noqa: F811
    stato = licenza.leggi(_licenza(chiavi, formula="inclusa", quota_utente="5.00", quota_istanza="120"))
    assert (stato.formula, stato.quota_utente, stato.quota_istanza) == ("inclusa", Decimal("5.00"), Decimal("120"))
    assert stato.nome_formula == "Assistente incluso nel canone"
    senza = licenza.leggi(_licenza(chiavi))
    assert senza.valida and (senza.formula, senza.quota_utente, senza.quota_istanza) == ("propria", 0, 0)
    # ciò che è scritto male non vale e non rompe la licenza
    strana = licenza.leggi(_licenza(chiavi, formula="regalo", quota_utente="tanto", quota_istanza="-3"))
    assert strana.valida and (strana.formula, strana.quota_utente, strana.quota_istanza) == ("propria", 0, 0)
    assert licenza.leggi(_licenza(chiavi, formula=["inclusa"], quota_utente="NaN", quota_istanza=[1])).formula == "propria"
    assert licenza.termini("non un dizionario") == {"formula": "propria", "quota_utente": 0, "quota_istanza": 0}


def test_termini_dalla_licenza_dell_istanza(db, chiavi):  # noqa: F811
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    privata = load_pem_private_key(chiavi.read_bytes(), None)
    base = {"cliente": "Rossi Srl", "moduli": ["ai"], "scadenza": (timezone.localdate() + datetime.timedelta(days=30)).isoformat()}

    def salva(minuti, **altri):
        emessa = (timezone.now() + datetime.timedelta(minutes=minuti)).isoformat()
        return licenza_istanza.salva(json.dumps(licenza_istanza.firma({**base, "emessa": emessa, **altri}, privata)))

    salva(0)
    assert licenza.attuale().formula == "propria"                    # la chiave "ai" non c'è: come prima delle formule
    assert salva(1, ai={"formula": "consumo", "quota_istanza": "50"}).valida    # il kernel non la legge, ma la firma la copre
    stato = licenza.attuale()
    assert stato.valida and (stato.formula, stato.quota_utente, stato.quota_istanza) == ("consumo", 0, Decimal("50"))
    salva(2, ai="inclusa")                                            # scritta male: nessun termine
    assert licenza.attuale().formula == "propria"


def test_comando_con_la_formula(db, chiavi, tmp_path):  # noqa: F811
    uscita = tmp_path / "licenza.json"
    comuni = ["--chiave", str(chiavi), "--cliente", "X", "--scadenza", "2099-12-31", "--uscita", str(uscita)]
    call_command("ai_licenza", *comuni, "--formula", "inclusa", "--quota-utente", "5", "--quota-istanza", "80.50", stdout=io.StringIO())
    stato = licenza.leggi(uscita.read_text())
    assert stato.valida and (stato.formula, stato.quota_utente, stato.quota_istanza) == ("inclusa", 5, Decimal("80.50"))
    call_command("ai_licenza", *comuni, stdout=io.StringIO())
    assert "formula" not in json.loads(uscita.read_text())["licenza"]          # senza opzioni la licenza è quella di sempre
    with pytest.raises(CommandError, match="quote valgono"):
        call_command("ai_licenza", *comuni, "--quota-utente", "5")
    with pytest.raises(CommandError, match="non è un numero"):
        call_command("ai_licenza", *comuni, "--formula", "consumo", "--quota-istanza", "tanto")


# ---------- il costo sul piano ----------

def test_il_costo_sul_piano_si_conta_a_parte(db, monkeypatch):
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    piano, proprio = _modello("Piano", gestito=True), _modello("Proprio")
    _catena(piano, proprio)
    utente = User.objects.create_user("u")
    with finto.con_copione([["ciao"], ["Titolo"]]):
        primo = motore.avvia(Conversazione.objects.create(utente=utente), "ciao", utente)
    primo.refresh_from_db()
    assert primo.stato == "completato" and primo.modello == piano and primo.costo > 0 and primo.costo_fornito == primo.costo
    titolo = Turno.objects.get(compito="titoli")
    assert titolo.costo > 0 and titolo.costo_fornito == titolo.costo          # anche i lavori di contorno
    assert limiti.consumo_fornito() == primo.costo + titolo.costo == limiti.consumo_fornito(utente)
    # il modello del piano rifiuta la richiesta: risponde quello proprio, e quel costo non è sul piano
    with finto.con_copione([[("errore", "RICHIESTA")], ["dal modello proprio"], [("errore", "RICHIESTA")], ["Titolo"]]):
        secondo = motore.avvia(Conversazione.objects.create(utente=utente), "ancora", utente)
    secondo.refresh_from_db()
    assert secondo.modello == proprio and secondo.costo > 0 and secondo.costo_fornito == 0
    assert limiti.consumo_fornito() == primo.costo + titolo.costo


def test_la_chiave_dell_azienda_non_vale_sul_provider_del_piano(db):
    azienda = Azienda.objects.get(pk=1)
    piano = Provider.objects.create(nome="Piano", tipo="anthropic", gestito=True, chiave_cifrata=cifratura.cifra("sk-ant-fornita"))
    proprio = Provider.objects.create(nome="Proprio", tipo="anthropic", chiave_cifrata=cifratura.cifra("sk-ant-globale"))
    for provider in (piano, proprio):
        ChiaveAzienda.objects.create(provider=provider, azienda=azienda, chiave_cifrata=cifratura.cifra("sk-ant-azienda"))
    assert piano.chiave_per(azienda) == "sk-ant-fornita" and proprio.chiave_per(azienda) == "sk-ant-azienda"


def test_eliminare_la_chat_non_azzera_il_consumo(db):
    utente = User.objects.create_user("u")
    chat = Conversazione.objects.create(utente=utente)
    turno = Turno.objects.create(conversazione=chat, utente=utente, costo=Decimal("2"), costo_fornito=Decimal("1.5"),
                                 testo="una risposta con dati", errore="un errore con dati", stato=Turno.COMPLETATO,
                                 avanzamento=[{"strumento": "cerca_record", "stato": "fatto"}],
                                 provenienza={"letture": [{"titolo": "Contatti", "dettaglio": "filtri: Mario Rossi"}]})
    Evento.objects.create(conversazione=chat, turno=turno, tipo=Evento.UTENTE, dati={"ruolo": "utente", "testo": "x"})
    altra = Conversazione.objects.create(utente=utente)
    resta = Turno.objects.create(conversazione=altra, utente=utente, testo="resta")
    chat.delete()
    turno.refresh_from_db()
    resta.refresh_from_db()
    assert turno.conversazione_id is None and turno.testo == "" and turno.errore == ""      # il costo sì, il contenuto no
    assert turno.avanzamento == [] and turno.provenienza == {}                             # nemmeno le ricerche fatte
    assert (turno.costo, turno.costo_fornito, turno.utente) == (Decimal("2"), Decimal("1.5"), utente)
    assert not Evento.objects.exists() and resta.conversazione == altra and resta.testo == "resta"
    assert limiti.consumo_fornito(utente) == Decimal("1.5")
    Conversazione.objects.filter(pk=altra.pk).delete()                                     # anche in blocco
    resta.refresh_from_db()
    assert resta.conversazione_id is None and resta.testo == ""


# ---------- le quote ----------

def test_quota_per_utente(db, chiavi):  # noqa: F811
    _con_formula(chiavi, formula="inclusa", quota_utente="1")
    piano, proprio = _modello("Piano", gestito=True), _modello("Proprio")
    tutti, solo_piano = [(piano, ""), (proprio, "")], [(piano, "")]
    anna, bruno = User.objects.create_user("anna"), User.objects.create_user("bruno")
    Turno.objects.create(utente=anna, costo=Decimal("0.99"), costo_fornito=Decimal("0.99"))
    Turno.objects.create(utente=anna, costo=Decimal("9"))                      # su una chiave propria: non conta
    Turno.objects.create(utente=anna, costo=Decimal("9"), costo_fornito=Decimal("9"), compito=limiti.SERVIZIO)   # la chat del sito
    assert limiti.ammessi(tutti, anna) == tutti and "usati 0.99 $ su 1 $ della tua quota" in limiti.avviso_quota(anna)
    Turno.objects.create(utente=anna, costo=Decimal("0.01"), costo_fornito=Decimal("0.01"))
    assert limiti.ammessi(tutti, anna) == [(proprio, "")]                      # la chat continua sul modello proprio
    with pytest.raises(ErroreModello, match="Hai esaurito la tua quota mensile") as errore:
        limiti.ammessi(solo_piano, anna)
    assert errore.value.codice == "LIMITE" and "primo del mese" in limiti.avviso_quota(anna)
    assert limiti.ammessi(solo_piano, bruno) == solo_piano and limiti.avviso_quota(bruno) == ""
    assert limiti.ammessi([(proprio, "")], anna) == [(proprio, "")]            # senza modelli del piano non c'è niente da togliere
    assert limiti.ammessi(solo_piano) == solo_piano                            # lavoro di servizio: conta solo l'istanza
    # il mese scorso non conta
    Turno.objects.filter(utente=anna).update(iniziato=timezone.now() - datetime.timedelta(days=40))
    assert limiti.ammessi(solo_piano, anna) == solo_piano


def test_quota_dell_istanza_e_tetto_a_consumo(db, chiavi):  # noqa: F811
    piano = _modello("Piano", gestito=True)
    solo_piano = [(piano, "")]
    anna, bruno = User.objects.create_user("anna"), User.objects.create_user("bruno")
    Turno.objects.create(utente=anna, costo=Decimal("2"), costo_fornito=Decimal("2"))
    _con_formula(chiavi, formula="inclusa", quota_utente="5", quota_istanza="2")
    with pytest.raises(ErroreModello, match="compresa nel piano è esaurita"):
        limiti.ammessi(solo_piano, bruno)                                      # finita per tutti, anche per chi non ha consumato
    _con_formula(chiavi, formula="consumo", quota_utente="1", quota_istanza="2")
    with pytest.raises(ErroreModello, match="tetto mensile dell'assistente previsto dal piano"):
        limiti.ammessi(solo_piano, bruno)
    _con_formula(chiavi, formula="consumo", quota_utente="1")                  # a consumo la quota per utente non c'è
    assert limiti.ammessi(solo_piano, anna) == solo_piano and limiti.quota(anna) == []
    _con_formula(chiavi)                                                       # chiave del cliente: come prima delle formule
    assert limiti.ammessi(solo_piano, anna) == solo_piano and limiti.avviso_quota(anna) == ""


def test_il_motore_rispetta_la_quota(db, chiavi, monkeypatch):  # noqa: F811
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    _con_formula(chiavi, formula="inclusa", quota_utente="1")
    piano = _modello("Piano", gestito=True)
    _catena(piano)
    utente = User.objects.create_user("u")
    Turno.objects.create(utente=utente, costo=Decimal("1"), costo_fornito=Decimal("1"))
    with finto.con_copione([["non arriva"]]) as chiamate:
        turno = motore.avvia(Conversazione.objects.create(utente=utente), "ciao", utente)
    turno.refresh_from_db()
    assert turno.stato == "errore" and "Hai esaurito la tua quota mensile" in turno.testo and not chiamate
    proprio = _modello("Proprio")
    AnelloCatena.objects.create(profilo=Profilo.objects.get(compito="chat"), modello=proprio, ordine=2)
    with finto.con_copione([["eccomi"], ["Titolo"]]) as chiamate:
        turno = motore.avvia(Conversazione.objects.create(utente=utente), "ciao", utente)
    turno.refresh_from_db()
    assert turno.stato == "completato" and turno.modello == proprio and {c["modello"] for c in chiamate} == {"proprio"}


# ---------- chi tocca i provider del piano ----------

def test_il_provider_del_piano_lo_cambia_solo_il_global_admin(client, amministratore):
    piano = _modello("Piano", gestito=True)
    proprio = _modello("Proprio")
    fornito, suo = piano.provider, proprio.provider
    assert client.get(f"/ai/provider/{fornito.pk}/modifica/").status_code == 403
    assert client.post(f"/ai/provider/{fornito.pk}/modifica/", {"nome": "Piano", "tipo": "openai_compat", "base_url": "https://ladro.example/v1",
                                                                "attivo": "on"}).status_code == 403
    assert client.post(f"/ai/provider/{fornito.pk}/elimina/").status_code == 403
    assert client.get(f"/ai/provider/{fornito.pk}/catalogo/").status_code == 403
    assert client.get(f"/ai/modelli/{piano.pk}/modifica/").status_code == 403
    assert client.post(f"/ai/modelli/{piano.pk}/elimina/").status_code == 403
    fornito.refresh_from_db()
    assert fornito.base_url == "" and fornito.tipo == "finto" and Modello.objects.filter(pk=piano.pk).exists()
    dettaglio = client.get(f"/ai/provider/{fornito.pk}/").content.decode()
    assert "Fornito con il piano" in dettaglio and "Nuovo modello" not in dettaglio
    # sui suoi provider lavora come prima, ma non può dichiararli «forniti con il piano» né spostarci un modello
    assert 'name="gestito"' not in client.get("/ai/provider/nuovo/").content.decode()
    r = client.post(f"/ai/provider/{suo.pk}/modifica/", {"nome": "Proprio 2", "tipo": "finto", "attivo": "on", "gestito": "on"})
    suo.refresh_from_db()
    assert r.status_code == 302 and suo.nome == "Proprio 2" and not suo.gestito
    dati = {"provider": fornito.pk, "id_api": "gratis", "etichetta": "Gratis", "contesto": 1000, "max_output": 100, "prezzo_input": "0",
            "prezzo_output": "0", "attivo": "on"}
    assert client.post("/ai/modelli/nuovo/", dati).status_code == 200 and not Modello.objects.filter(id_api="gratis").exists()
    assert client.post(f"/ai/modelli/{proprio.pk}/modifica/", {**dati, "id_api": "proprio"}).status_code == 200
    proprio.refresh_from_db()
    assert proprio.provider == suo
    # la chiave dell'azienda non si mette su un provider del piano: non varrebbe
    modulo = client.get("/ai/chiavi/nuovo/").content.decode()
    assert "Proprio 2" in modulo and ">Piano<" not in modulo


def test_il_global_admin_gestisce_il_provider_del_piano(client, superuser):
    piano = _modello("Piano", gestito=True)
    fornito = piano.provider
    assert 'name="gestito"' in client.get("/ai/provider/nuovo/").content.decode()
    r = client.post(f"/ai/provider/{fornito.pk}/modifica/", {"nome": "Piano", "tipo": "finto", "attivo": "on", "gestito": "on", "nuova_chiave": "k-123456"})
    fornito.refresh_from_db()
    assert r.status_code == 302 and fornito.gestito and fornito.chiave_per() == "k-123456"
    assert client.get(f"/ai/modelli/{piano.pk}/modifica/").status_code == 200
    assert "Nuovo modello" in client.get(f"/ai/provider/{fornito.pk}/").content.decode()
    elenco = client.get("/ai/provider/").content.decode()
    assert "del piano" in elenco and "3456" not in elenco           # della chiave del piano nemmeno le ultime cifre


def test_i_consumi_non_si_eliminano(client, superuser):
    turno = Turno.objects.create(utente=superuser, costo=Decimal("1"), costo_fornito=Decimal("1"))
    assert client.post(f"/ai/consumi/{turno.pk}/elimina/").status_code == 403 and Turno.objects.filter(pk=turno.pk).exists()
    assert "Sul piano" in client.get("/ai/consumi/").content.decode()


# ---------- ciò che si vede ----------

def test_avviso_in_chat_e_pagina_della_licenza(client, superuser, chiavi):  # noqa: F811
    _con_formula(chiavi, formula="inclusa", quota_utente="10", quota_istanza="100")
    Turno.objects.create(utente=superuser, costo=Decimal("9"), costo_fornito=Decimal("9"))
    assert "usati 9.00 $ su 10 $ della tua quota mensile" in client.get("/ai/chat/").content.decode()
    pagina = client.get("/ai/licenza/").content.decode()
    assert "Assistente incluso nel canone" in pagina and "9,00 $ su 100 $" in pagina and "10 $ al mese" in pagina
    assert "Consumo del mese per utente" in pagina and "root" in pagina
    assert "Da sistemare" in pagina                    # la formula c'è ma nessun provider è «fornito con il piano»
    _modello("Piano", gestito=True)
    assert "Da sistemare" not in client.get("/ai/licenza/").content.decode()
    _con_formula(chiavi)
    pagina = client.get("/ai/licenza/").content.decode()
    assert "Chiave del cliente" in pagina and "Consumo del mese sul piano" not in pagina and "Da sistemare" not in pagina
    assert "quota mensile" not in client.get("/ai/chat/").content.decode()


# ---------- i consumi al portale ----------

def test_riepilogo_del_mese_e_invio_al_portale(db, settings, monkeypatch):
    anna, bruno = User.objects.create_user("anna"), User.objects.create_user("bruno")
    Turno.objects.create(utente=anna, costo=Decimal("2.5"), costo_fornito=Decimal("2"))
    Turno.objects.create(utente=anna, costo=Decimal("0.5"), compito="titoli")
    Turno.objects.create(utente=bruno, costo=Decimal("1"), costo_fornito=Decimal("1"))
    vecchio = Turno.objects.create(utente=bruno, costo=Decimal("7"), costo_fornito=Decimal("7"))
    questo, scorso = consumi_portale._mesi()
    Turno.objects.filter(pk=vecchio.pk).update(iniziato=timezone.make_aware(datetime.datetime(scorso.year, scorso.month, 15, 12)))
    assert consumi_portale.riepilogo(questo) == {"mese": f"{questo:%Y-%m}", "costo": "4.000000", "costo_fornito": "3.000000",
                                                 "turni": 3, "utenti": 2}
    assert consumi_portale.riepilogo(scorso)["costo_fornito"] == "7.000000"
    assert consumi_portale.invia() is None                                     # senza portale non parte niente
    settings.LICENZA_PORTALE_URL, settings.LICENZA_TOKEN = "https://portale.example/rivendita/api", "segreto"
    inviati = []
    monkeypatch.setattr(consumi_portale, "_chiama", inviati.append)
    assert consumi_portale.invia() == f"inviati: {questo:%Y-%m}, {scorso:%Y-%m}"
    assert [m["mese"] for m in inviati[0]["mesi"]] == [f"{questo:%Y-%m}", f"{scorso:%Y-%m}"]
    assert "anna" not in json.dumps(inviati[0])                                # numeri, non persone

    def giu(dati):
        raise urllib.error.URLError("portale spento")
    monkeypatch.setattr(consumi_portale, "_chiama", giu)
    assert "non arrivati al portale" in consumi_portale.invia()
    # con la sua chiave il cliente non riferisce quanto spende: parte solo ciò che è passato dal piano
    monkeypatch.setattr(consumi_portale, "_chiama", inviati.append)
    Turno.objects.filter(pk=vecchio.pk).update(costo_fornito=0)
    assert consumi_portale.invia() == f"inviati: {questo:%Y-%m}" and len(inviati) == 2
    Turno.objects.update(costo_fornito=0)
    assert consumi_portale.invia() is None and len(inviati) == 2
