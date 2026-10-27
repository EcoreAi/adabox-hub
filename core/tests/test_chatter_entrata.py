from email.message import EmailMessage

import pytest
from django.contrib.auth.models import Permission, User

from core import chatter
from core.chatter import email as posta
from core.chatter import entrata
from core.generici import ct_di
from core.models import Allegato, Azienda, EmailRicevuta, Messaggio


@pytest.fixture(autouse=True)
def ambiente(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    settings.EMAIL_RISPOSTE = "risposte@example.com"


@pytest.fixture
def scena(db):
    acme = Azienda.objects.create(nome="Acme")
    lettore = User.objects.create_user("lucia", "Lucia@Example.com", "x")
    lettore.user_permissions.add(Permission.objects.get(codename="view_azienda"))
    originale = chatter.scrivi(acme, None, "Domanda?", tipo="sistema")
    originale.message_id = "<msg-1-abcdef@hub.example.com>"
    originale.save()
    return acme, lettore, originale


def _email(corpo="Risposta nuova", da="lucia@example.com", a="risposte@example.com", mid="<r1@client>",
           in_risposta=None, html=None, allegato=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = f"Lucia <{da}>", a, "Re: [Hub] Acme", mid
    if in_risposta:
        m["In-Reply-To"] = in_risposta
    if html:
        m.set_content(html, subtype="html")
    else:
        m.set_content(corpo)
    if allegato:
        m.add_attachment(allegato[1], maintype="application", subtype="octet-stream", filename=allegato[0])
    return m.as_bytes()


def test_abbinata_per_in_reply_to(scena):
    acme, lettore, originale = scena
    riga = entrata.ricevi(_email(in_risposta=originale.message_id))
    assert riga.stato == EmailRicevuta.ABBINATA
    m = riga.messaggio
    assert (m.autore, m.corpo, m.tipo, m.record) == (lettore, "Risposta nuova", Messaggio.MESSAGGIO, acme)
    assert chatter.segue(acme, lettore)


def test_abbinata_per_token(scena):
    acme, _, _ = scena
    indirizzo = posta.indirizzo_risposta(ct_di(acme).pk, acme.pk)
    assert entrata.ricevi(_email(a=indirizzo)).stato == EmailRicevuta.ABBINATA


def test_token_falsificato(scena):
    acme, _, _ = scena
    finto = f"risposte+{ct_di(acme).pk}-{acme.pk}-0123456789abcdef@example.com"
    riga = entrata.ricevi(_email(a=finto))
    assert riga.stato == EmailRicevuta.NON_ABBINATA and riga.messaggio is None


def test_riferimento_al_filo_non_basta(scena):
    acme, _, _ = scena
    riga = entrata.ricevi(_email(in_risposta=posta.riferimento_record(ct_di(acme).pk, acme.pk)))
    assert riga.stato == EmailRicevuta.NON_ABBINATA


def test_mittente_sconosciuto_o_senza_permesso(scena):
    _, _, originale = scena
    assert entrata.ricevi(_email(da="ignoto@example.com", in_risposta=originale.message_id)).stato == "rifiutata"
    User.objects.create_user("muto", "muto@example.com", "x")
    riga = entrata.ricevi(_email(da="muto@example.com", mid="<r2@c>", in_risposta=originale.message_id))
    assert riga.stato == EmailRicevuta.RIFIUTATA and "muto@example.com" in riga.motivo


def test_record_di_un_azienda_non_consentita(scena, monkeypatch):
    acme, lettore, originale = scena
    from core.viste import registry
    vista = registry.per_modello(Azienda)
    monkeypatch.setattr(vista, "get_queryset", lambda request: Azienda.objects.exclude(pk=acme.pk))
    assert entrata.ricevi(_email(in_risposta=originale.message_id)).stato == EmailRicevuta.RIFIUTATA


@pytest.mark.parametrize("testo", [
    "Va bene, procedo.\n\nIl giorno lun 27 ott 2026 alle 10:00 Anna <a@b.it> ha scritto:\n> Domanda?",
    "Va bene, procedo.\n\nIl giorno lun 27 ott 2026 alle 10:00 Anna <a@b.it>\nha scritto:\n> Domanda?",
    "Va bene, procedo.\n\nOn Mon, Oct 27, 2026 at 10:00 AM Anna <a@b.it> wrote:\n> Question?",
    "Va bene, procedo.\n-----Original Message-----\nFrom: Anna",
    "Va bene, procedo.\n> citato",
])
def test_citazione_tolta(testo):
    assert entrata.togli_citazione(testo) == "Va bene, procedo."


def test_solo_html(scena):
    _, _, originale = scena
    riga = entrata.ricevi(_email(html="<p>Prima riga</p><p>Seconda &amp; ultima</p>", in_risposta=originale.message_id))
    assert riga.messaggio.corpo == "Prima riga\nSeconda & ultima"


def test_allegati(scena):
    acme, _, originale = scena
    riga = entrata.ricevi(_email(in_risposta=originale.message_id, allegato=("preventivo.pdf", b"%PDF-1.4")))
    assert riga.messaggio.allegati.get().nome == "preventivo.pdf"
    riga = entrata.ricevi(_email(mid="<r3@c>", in_risposta=originale.message_id, allegato=("x.exe", b"MZ")))
    assert riga.stato == EmailRicevuta.ABBINATA and "non ammessi" in riga.motivo
    assert Allegato.objects.count() == 1


def test_doppione(scena):
    _, _, originale = scena
    grezza = _email(in_risposta=originale.message_id)
    prima, seconda = entrata.ricevi(grezza), entrata.ricevi(grezza)
    assert prima.pk == seconda.pk and Messaggio.objects.filter(tipo="messaggio").count() == 1


def test_vuota_rifiutata(scena):
    _, _, originale = scena
    assert entrata.ricevi(_email(corpo="\n> solo citazione", in_risposta=originale.message_id)).stato == "rifiutata"


class _ImapFinto:
    def __init__(self, messaggi):
        self.messaggi, self.chiamate = messaggi, []

    def login(self, utente, password):
        self.chiamate.append(("login", utente, password))

    def select(self, cartella):
        self.chiamate.append(("select", cartella))

    def search(self, charset, criterio):
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.messaggi)))]

    def fetch(self, numero, parti):
        return "OK", [(b"1 (BODY[] {n})", self.messaggi[int(numero) - 1])]

    def store(self, numero, op, flag):
        self.chiamate.append(("store", numero, flag))

    def close(self):
        pass

    def logout(self):
        self.chiamate.append(("logout",))


def test_leggi_casella(scena, settings, monkeypatch):
    _, _, originale = scena
    assert entrata.leggi_casella() == 0                       # senza IMAP_URL
    settings.IMAP_URL = "imaps://risposte%40example.com:p%40ss@mail.example.com/Posta"
    finto = _ImapFinto([_email(in_risposta=originale.message_id), _email(mid="<r9@c>")])
    monkeypatch.setattr(entrata.imaplib, "IMAP4_SSL", lambda host, porta: finto)
    assert entrata.leggi_casella() == 2
    assert ("login", "risposte@example.com", "p@ss") in finto.chiamate and ("select", "Posta") in finto.chiamate
    assert [c for c in finto.chiamate if c[0] == "store"] == [("store", b"1", "\\Seen"), ("store", b"2", "\\Seen")]
    assert sorted(EmailRicevuta.objects.values_list("stato", flat=True)) == ["abbinata", "non_abbinata"]


@pytest.mark.django_db
def test_pagina_email_ricevute(client, superuser):
    assert client.get("/core/email/").status_code == 200
