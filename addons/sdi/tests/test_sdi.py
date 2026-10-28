import io
import zipfile
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

import fiscale
import prodotti
from contatti.models import Contatto
from core import parametri
from core.models import Azienda, Messaggio
from fatturazione import fatturapa, operazioni
from fatturazione.models import DatiFiscali, Fattura, RigaFattura
from fiscale.models import AliquotaIva
from prodotti.models import Prodotto
from sdi import canali, hooks, notifiche, pec, servizi, validazione
from sdi.models import NotificaSdi, Trasmissione

NS = canali.NS_MESSAGGI


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    azienda.nome, azienda.partita_iva, azienda.indirizzo = "Ichnobyte Srl", "01234567897", "Via Roma 1"
    azienda.cap, azienda.citta, azienda.provincia = "00100", "Roma", "RM"
    azienda.save()
    DatiFiscali.objects.create(azienda=azienda, iban="IT60X0542811101000000123456")
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, partita_iva="12345678903",
                                      indirizzo="Corso Italia 5", cap="20100", citta="Milano", provincia="MI")
    monitor = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("199.99"))
    corso = Prodotto.objects.create(azienda=azienda, nome="Corso", tipo="servizio", prezzo_vendita=Decimal("100"),
                                    aliquota_iva=AliquotaIva.objects.get(codice="N4"))
    f = Fattura.objects.create(azienda=azienda, cliente=cliente)
    RigaFattura.objects.create(fattura=f, prodotto=monitor, quantita=2, sconto=10)
    RigaFattura.objects.create(fattura=f, prodotto=corso)
    f.ricalcola()
    operazioni.emetti(f)
    return azienda, cliente, f


def _notifica(radice, nome_file, identificativo="111222333", extra=""):
    return (f'<?xml version="1.0" encoding="UTF-8"?><ns:{radice} xmlns:ns="{NS}" versione="1.0">'
            f"<IdentificativoSdI>{identificativo}</IdentificativoSdI><NomeFile>{nome_file}</NomeFile>"
            f"<DataOraRicezione>2026-10-28T10:00:00</DataOraRicezione>{extra}</ns:{radice}>").encode()


def _carica(client, nome, contenuto):
    return client.post("/sdi/carica/", {"file": SimpleUploadedFile(nome, contenuto)})


def test_validazione_con_lo_schema(scena):
    _, _, f = scena
    _, xml = fatturapa.genera(f)
    assert validazione.errori(xml) == []
    rotto = xml.replace(b"<Divisa>EUR</Divisa>", b"")
    assert any("Divisa" in e for e in validazione.errori(rotto))
    assert validazione.errori(b"<non xml")[0].startswith("XML non leggibile")


def test_canale_manuale_fino_alla_consegna(client, superuser, scena):
    _, _, f = scena
    html = client.get(f"/fatturazione/fatture/{f.pk}/").content.decode()
    assert "Invia allo SDI" in html and "Non ancora inviata" in html
    client.post(f"/sdi/invia/{f.pk}/")
    t = Trasmissione.objects.get()
    assert t.stato == "pronta" and t.canale == "manuale" and t.nome_file == "IT01234567897_00001.xml"
    r = client.get(f"/sdi/trasmissione/{t.pk}/xml/")
    assert r["Content-Disposition"].endswith('"IT01234567897_00001.xml"') and b"FatturaElettronica" in r.content
    assert client.post(f"/sdi/invia/{f.pk}/", follow=True).content.decode().count("già una trasmissione") == 1
    client.post(f"/sdi/trasmissione/{t.pk}/caricata/")
    t.refresh_from_db()
    assert t.stato == "inviata" and t.inviata_il
    r = _carica(client, "IT01234567897_00001_RC_001.xml", _notifica("RicevutaConsegna", t.nome_file))
    assert "Ricevuta di consegna" in r.content.decode()
    t.refresh_from_db()
    assert t.stato == "consegnata" and t.identificativo_sdi == "111222333"
    assert Messaggio.objects.filter(object_id=f.pk, corpo__contains="consegnato").exists()
    r = _carica(client, "IT01234567897_00001_RC_001.xml", _notifica("RicevutaConsegna", t.nome_file))
    assert "già presente" in r.content.decode() and NotificaSdi.objects.count() == 1


def test_canale_di_prova(client, superuser, scena):
    azienda, _, f = scena
    parametri.scrivi("sdi.canale", "prova", azienda)
    client.post(f"/sdi/invia/{f.pk}/")
    t = Trasmissione.objects.get()
    assert t.stato == "consegnata" and t.canale == "prova" and t.notifiche.get().tipo == "RC"


def test_scarto_e_reinvio_con_nuovo_progressivo(client, superuser, scena):
    _, _, f = scena
    t, _ = servizi.invia(f)
    errore = "<ListaErrori><Errore><Codice>00305</Codice><Descrizione>IdFiscaleIVA del cessionario non valido" \
             "</Descrizione><Suggerimento>Verifica la partita IVA</Suggerimento></Errore></ListaErrori>"
    notifiche.registra(_notifica("NotificaScarto", t.nome_file, extra=errore), "IT01234567897_00001_NS_001.xml")
    t.refresh_from_db()
    assert t.stato == "scartata" and t.errori[0]["codice"] == "00305"
    html = client.get(f"/fatturazione/fatture/{f.pk}/").content.decode()
    assert "00305" in html and "Reinvia allo SDI" in html
    client.post(f"/sdi/invia/{f.pk}/")
    nuova = f.trasmissioni.order_by("-pk").first()
    assert nuova.nome_file == "IT01234567897_00002.xml" and f.trasmissioni.count() == 2


@pytest.mark.parametrize("radice,extra,stato", [
    ("NotificaMancataConsegna", "", "mancata"),
    ("NotificaEsito", "<EsitoCommittente><Esito>EC01</Esito></EsitoCommittente>", "accettata"),
    ("NotificaEsito", "<EsitoCommittente><Esito>EC02</Esito></EsitoCommittente>", "rifiutata"),
    ("NotificaDecorrenzaTermini", "", "decorsa"),
])
def test_altri_esiti(scena, radice, extra, stato):
    _, _, f = scena
    t, _ = servizi.invia(f)
    notifiche.registra(_notifica(radice, t.nome_file, extra=extra), f"IT01234567897_00001_XX_{radice[:3]}.xml")
    t.refresh_from_db()
    assert t.stato == stato


def test_notifica_senza_trasmissione_e_file_estranei(client, superuser, scena):
    r = _carica(client, "IT09999999999_00009_RC_001.xml", _notifica("RicevutaConsegna", "IT09999999999_00009.xml"))
    assert "nessuna trasmissione" in r.content.decode()
    r = _carica(client, "lista.xml", b"<spesa><uova/></spesa>")
    assert "non riconosciuto" in r.content.decode()


def test_zip_di_notifiche(client, superuser, scena):
    _, _, f = scena
    t, _ = servizi.invia(f)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("cartella/IT01234567897_00001_RC_001.xml", _notifica("RicevutaConsegna", t.nome_file))
        z.writestr("note.txt", "x")
    r = _carica(client, "notifiche.zip", buffer.getvalue())
    t.refresh_from_db()
    assert t.stato == "consegnata" and "non riconosciuto" in r.content.decode()


def test_xml_fuori_schema_non_parte(scena, monkeypatch):
    _, _, f = scena
    monkeypatch.setattr(fatturapa, "genera", lambda fattura: ("IT01234567897_00001.xml", b"<a/>"))
    with pytest.raises(ValidationError, match="schema FatturaPA"):
        servizi.invia(f)
    assert not Trasmissione.objects.exists()


def _busta_pec(mittente_sdi, nome, contenuto):
    interno = EmailMessage()
    interno["From"] = mittente_sdi
    interno["Subject"] = "Consegna"
    interno.set_content("Ricevuta")
    interno.add_attachment(contenuto, maintype="application", subtype="xml", filename=nome)
    busta = EmailMessage()
    busta["From"] = "posta-certificata@pec.fatturapa.it"
    busta["Subject"] = "POSTA CERTIFICATA: Consegna"
    busta.set_content("Messaggio di posta certificata")
    busta.add_attachment(b"<postacert/>", maintype="application", subtype="xml", filename="daticert.xml")
    busta.add_attachment(interno)
    return busta.as_bytes()


def test_pec_invio_e_lettura(scena, monkeypatch):
    azienda, _, f = scena
    for chiave, valore in [("canale", "pec"), ("pec_indirizzo", "fatture@pec.ichnobyte.it"),
                           ("pec_smtp", "smtps://u:p@smtps.pec.example:465"),
                           ("pec_imap", "imaps://u:p@imaps.pec.example:993/INBOX")]:
        parametri.scrivi(f"sdi.{chiave}", valore, azienda)
    from django.core.mail.backends.locmem import EmailBackend
    monkeypatch.setattr(pec, "connessione_smtp", lambda url: EmailBackend())
    t, _ = servizi.invia(f)
    inviata = mail.outbox[-1]
    assert t.stato == "inviata" and inviata.to == ["sdi01@pec.fatturapa.it"]
    assert inviata.from_email == "fatture@pec.ichnobyte.it" and inviata.attachments[0][0] == t.nome_file
    busta = _busta_pec("sdi23@pec.fatturapa.it", "IT01234567897_00001_RC_001.xml",
                       _notifica("RicevutaConsegna", t.nome_file))

    class FintaImap:
        letti = []

        def search(self, *a):
            return "OK", [b"1"]

        def fetch(self, numero, cosa):
            return "OK", [(b"1", busta)]

        def store(self, numero, *a):
            self.letti.append(numero)

        def close(self):
            pass

        def logout(self):
            pass

    finta = FintaImap()
    monkeypatch.setattr(pec, "_imap", lambda url: finta)
    assert pec.leggi_tutte() == "messaggi elaborati: 1" and finta.letti == [b"1"]
    t.refresh_from_db()
    assert t.stato == "consegnata"
    assert parametri.leggi("sdi.indirizzo_sdi", azienda) == "sdi23@pec.fatturapa.it"       # per i prossimi invii


def test_errore_di_invio_resta_tracciato(scena, monkeypatch):
    azienda, _, f = scena
    parametri.scrivi("sdi.canale", "pec", azienda)                     # senza configurazione
    with pytest.raises(ValidationError, match="Configura"):
        servizi.invia(f)
    t = Trasmissione.objects.get()
    assert t.stato == "errore" and servizi.puo_inviare(f)


def test_demo_e_dashboard(rf, superuser, scena):
    from sdi.dashboard import kpi
    hooks.demo(None)
    hooks.demo(None)
    assert Trasmissione.objects.get().stato == "consegnata"
    richiesta = rf.get("/")
    richiesta.user, richiesta.azienda = superuser, scena[0]
    assert kpi(richiesta)["kpi"][0]["valore"] == 0
