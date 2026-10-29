import re

import pytest
from django.contrib.auth.models import Permission, User

from ai import motore, protezione, provenienza, strumenti
from ai.gateway import finto
from ai.models import AnelloCatena, Conversazione, Evento, Modello, Profilo, Proposta, Provider, Turno
from core import parametri
from core.models import Azienda

NOMI = re.compile(r"Mario Rossi|Anna Verdi|[\w.]+@[\w.]+\.\w+|RSSMRA80A01H501U")


def finto_servizio(url, testo, esclusi):
    """Riconosce due nomi, le email e un codice fiscale; registra i testi analizzati."""
    finto_servizio.testi.append(testo)
    etichette = {"@": "EMAIL", "RSS": "CF"}
    return [(m.start(), m.end(), next((e for k, e in etichette.items() if k in m.group()), "FULLNAME"))
            for m in NOMI.finditer(testo)]


@pytest.fixture
def scena(db, client, monkeypatch):
    finto_servizio.testi = []
    monkeypatch.setattr(protezione, "_analizza", finto_servizio)
    protezione._cache.clear()
    parametri.scrivi("ai.url_pii", "http://pii-finto:5005")
    cloud = Provider.objects.create(nome="Cloud", tipo="finto", locale=False)
    locale = Provider.objects.create(nome="Locale", tipo="finto", locale=True)
    m_cloud = Modello.objects.create(provider=cloud, id_api="cloud-1", etichetta="Cloud")
    m_locale = Modello.objects.create(provider=locale, id_api="locale-1", etichetta="Locale")
    profilo = Profilo.objects.create(nome="Chat", compito="chat")
    AnelloCatena.objects.create(profilo=profilo, modello=m_cloud, ordine=1)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    return {"capo": capo, "azienda": Azienda.objects.get(pk=1), "profilo": profilo, "locale": m_locale,
            "cloud": m_cloud, "client": client, "conversazione": Conversazione.objects.create(utente=capo)}


def _avvia(scena, testo):
    return motore.avvia(scena["conversazione"], testo, scena["capo"], scena["azienda"])


def test_vault_stabile_e_smascheramento_tollerante():
    v = protezione.Vault()
    assert v.segnaposto("FULLNAME", "Mario Rossi") == "[FULLNAME_1]"
    assert v.segnaposto("ORG", "mario  rossi") == "[FULLNAME_1]"                  # stesso valore, stesso segnaposto
    assert v.segnaposto("EMAIL", "a@b.it") == "[EMAIL_1]"
    testo = "Ciao [fullname 1], scrivi a [ EMAIL_1 ] o vedi [qui](EMAIL_1) e [IBAN_9]"
    assert v.smaschera(testo) == ("Ciao Mario Rossi, scrivi a a@b.it o vedi [qui](a@b.it) e [IBAN_9]", 1)
    assert protezione.Vault(v.mappa).segnaposto("FULLNAME", "Anna Verdi") == "[FULLNAME_2]"   # dal salvato


def test_plausibilita_nei_risultati_degli_strumenti():
    testo = '{"Mario Rossi": 1, "cliente": "SYN-KIT", "cap": "27600"}'

    def dove(valore):
        return testo.index(valore), testo.index(valore) + len(valore)
    assert not protezione.plausibile(testo, *dove("Mario Rossi"), "FULLNAME")      # chiave JSON
    assert not protezione.plausibile(testo, *dove("SYN-KIT"), "ORG")               # un codice non è un'azienda
    assert not protezione.plausibile(testo, *dove("27600"), "FULLNAME")            # un numero non è un nome
    assert protezione.plausibile("Il cliente Mario Rossi", 11, 22, "FULLNAME")


def test_al_cloud_solo_segnaposto_all_utente_in_chiaro(scena):
    ricevuti = []
    strumenti.registra(strumenti.Strumento("eco", "test", {"type": "object", "properties": {}},
                                           lambda c, **kw: ricevuti.append(kw) or {"trovato": kw}))
    try:
        with finto.con_copione([[("strumento", "eco", {"cliente": "[FULLNAME_1]"})],
                                ["Ho scritto a [FULL", "NAME_1] all'indirizzo [EMAIL_1]."]]) as chiamate:
            turno = _avvia(scena, "Scrivi a Mario Rossi, email mario.rossi@example.com")
    finally:
        strumenti.registro._registro.pop("eco")
    turno.refresh_from_db()
    inviati = str(chiamate[0]["messaggi"]) + str(chiamate[1]["messaggi"])
    assert "Mario Rossi" not in inviati and "mario.rossi@example.com" not in inviati and "[FULLNAME_1]" in inviati
    assert "segnaposto" in chiamate[0]["sistema"]
    assert ricevuti == [{"cliente": "Mario Rossi"}]                                   # lo strumento lavora in chiaro
    assert turno.testo == "Ho scritto a Mario Rossi all'indirizzo mario.rossi@example.com."
    assistente = Evento.objects.filter(tipo="assistente").first()
    assert assistente.dati["mascherato"] and assistente.dati["blocchi"][0]["argomenti"] == {"cliente": "Mario Rossi"}
    scena["conversazione"].refresh_from_db()
    assert scena["conversazione"].segnaposto == {"[FULLNAME_1]": "Mario Rossi", "[EMAIL_1]": "mario.rossi@example.com"}
    assert turno.provenienza["pii"] >= 2


def test_modello_locale_in_chiaro(scena):
    AnelloCatena.objects.filter(profilo=scena["profilo"]).update(modello=scena["locale"])
    with finto.con_copione([["Ok."]]) as chiamate:
        _avvia(scena, "Chiama Mario Rossi")
    assert "Mario Rossi" in chiamate[0]["messaggi"][0]["testo"] and not finto_servizio.testi
    assert "segnaposto" not in chiamate[0]["sistema"]


def test_servizio_giu_niente_al_cloud(scena, monkeypatch):
    def giu(url, testo, esclusi):
        raise protezione.ServizioNonDisponibile("connessione rifiutata")
    monkeypatch.setattr(protezione, "_analizza", giu)
    with finto.con_copione([["Non deve arrivare."]]) as chiamate:
        turno = _avvia(scena, "Chiama Mario Rossi")
    turno.refresh_from_db()
    assert chiamate == [] and turno.stato == "errore" and "protegge i dati personali" in turno.testo
    AnelloCatena.objects.create(profilo=scena["profilo"], modello=scena["locale"], ordine=2)   # riserva locale
    with finto.con_copione([["Risponde il locale."]]) as chiamate:
        turno = _avvia(scena, "Chiama Mario Rossi")
    turno.refresh_from_db()
    assert {c["modello"] for c in chiamate} == {"locale-1"} and turno.testo == "Risponde il locale."   # anche il titolo


def test_titoli_protetti(scena):
    Profilo.objects.create(nome="Titoli", compito="titoli")
    AnelloCatena.objects.create(profilo=Profilo.objects.get(compito="titoli"), modello=scena["cloud"])
    with finto.con_copione([["Fatto."], ["Telefonata a [FULLNAME_1]"]]) as chiamate:
        _avvia(scena, "Chiama Mario Rossi")
    assert "Mario Rossi" not in str(chiamate[1]["messaggi"])
    scena["conversazione"].refresh_from_db()
    assert scena["conversazione"].titolo == "Telefonata a Mario Rossi"


def test_guardia_sui_numeri():
    assert [v for _, v in provenienza.numeri("Totale 1.234,56 € il 12/10/2026 per [S00012](/vendite/ordini/12/)")] \
        == [provenienza.Decimal("1234.56")]
    fonti = [v for _, v in provenienza.numeri('{"totale": "1234.50", "righe": 3}', italiano=False)]
    assert provenienza._trovato(provenienza.Decimal("1234.50"), fonti)
    assert provenienza._trovato(provenienza.Decimal("1235"), fonti)                  # arrotondato
    assert not provenienza._trovato(provenienza.Decimal("99.99"), fonti)


def test_provenienza_e_badge(scena):
    AnelloCatena.objects.filter(profilo=scena["profilo"]).update(modello=scena["locale"])
    with finto.con_copione([[("strumento", "aggrega_record", {"vista": "core.aziende", "per": "provincia"})],
                            ["Ci sono 1 aziende, fatturato 4.321,00 €."]]):
        turno = _avvia(scena, "Quante aziende?")
    turno.refresh_from_db()
    assert turno.provenienza["esito"] == "parziale" and turno.provenienza["non_verificati"] == ["4.321,00"]
    assert turno.provenienza["strumenti"] == ["aggrega_record"] and turno.provenienza["letture"] == 1
    html = scena["client"].get(f"/ai/chat/{scena['conversazione'].pk}/").content.decode()
    assert "Dati dal gestionale (1 letture)" in html and "1 numero non trovato nei dati letti" in html
    assert "Locale ·" in html                                                        # modello e costo per chi vede i consumi
    with finto.con_copione([["Ciao!"]]):
        turno = _avvia(scena, "Ciao")
    turno.refresh_from_db()
    assert turno.provenienza["esito"] == "conversazione"


def test_registro_delle_modifiche(scena, client):
    Proposta.objects.create(conversazione=scena["conversazione"], utente=scena["capo"], strumento="crea_record",
                            titolo="Crea azienda «Delta»", stato="eseguita", esito="Creato.")
    r = scena["client"].get("/ai/registro/")
    assert r.status_code == 200 and "Crea azienda «Delta»" in r.content.decode()
    assert scena["client"].get("/ai/registro/nuovo/").status_code == 403
    utente = User.objects.create_user("utente", password="x")
    utente.user_permissions.add(Permission.objects.get(codename="view_conversazione"))
    client.force_login(utente)
    assert client.get("/ai/registro/").status_code == 403
    assert Turno.objects.model._meta.get_field("provenienza")


def test_risposta_del_servizio_vero(monkeypatch):
    """Il formato di adabox-pii: testo senza spazi ai bordi, segmenti con il testo originale."""
    import io
    import json

    def risposta(segmenti):
        class Finta(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return lambda richiesta, timeout: Finta(json.dumps({"segments": segmenti}).encode())
    monkeypatch.setattr(protezione.urllib.request, "urlopen", risposta([
        {"t": "Scrivi a "}, {"label": "FULLNAME", "ph": "[FULLNAME_1]", "t": "Mario Rossi"}, {"t": " oggi"}]))
    testo = "  Scrivi a Mario Rossi oggi\n"
    (inizio, fine, etichetta), = protezione._analizza("http://pii", testo, ())
    assert testo[inizio:fine] == "Mario Rossi" and etichetta == "FULLNAME"
    monkeypatch.setattr(protezione.urllib.request, "urlopen", risposta([{"label": "FULLNAME", "ph": "[FULLNAME_1]"}]))
    with pytest.raises(protezione.ServizioNonDisponibile, match="senza testo"):
        protezione._analizza("http://pii", "Mario Rossi", ())
    monkeypatch.setattr(protezione.urllib.request, "urlopen", risposta([{"t": "Mario"}]))
    with pytest.raises(protezione.ServizioNonDisponibile, match="non ricostruiscono"):
        protezione._analizza("http://pii", "Mario Rossi", ())
