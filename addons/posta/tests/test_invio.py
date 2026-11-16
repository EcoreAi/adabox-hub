"""I messaggi del chatter ai clienti dalla casella di chi scrive, e le risposte che tornano allo stesso record."""
import pytest
from django.utils import timezone

from core import cifratura
from core.chatter import scrivi
from core.models import Messaggio
from crm.models import Opportunita
from posta import sincronia
from posta.fornitori.google import Google
from posta.fornitori.microsoft import Microsoft
from posta.models import Casella

from .finti import messaggio
from .test_posta import IO, _storico, _utente, anna, azienda, cliente, google, microsoft, servizi  # noqa: F401

pytestmark = pytest.mark.django_db
TUTTI = {"google": " ".join(Google.AMBITI), "microsoft": " ".join(Microsoft.AMBITI)}


def _casella(azienda, utente, tipo="google", **campi):
    campi = {"ambiti": TUTTI[tipo], **campi}
    return Casella.objects.create(azienda=azienda, utente=utente, tipo=tipo, email=IO, refresh_cifrato=cifratura.cifra("ref-1"), **campi)


def _al_cliente(cliente, anna, testo="Le mando l'offerta aggiornata."):
    return scrivi(cliente, anna, testo, destinatari=["luca@verdi.it"])


def test_il_messaggio_al_cliente_parte_dalla_casella_dell_autore(azienda, anna, servizi, google, cliente, mailoutbox):
    anna.first_name, anna.last_name = "Anna", "Rossi"
    anna.save()
    _casella(azienda, anna)
    m = _al_cliente(cliente, anna)
    m.refresh_from_db()
    inviato, = google.inviati
    assert inviato["To"] == "luca@verdi.it" and inviato["From"] == f"Anna Rossi <{IO}>" and inviato["Reply-To"] is None
    assert inviato["Message-ID"] == m.message_id and "offerta aggiornata" in inviato.get_body(("plain",)).get_content()
    assert not [e for e in mailoutbox if "luca@verdi.it" in e.to]                         # non anche dal server


def test_senza_il_permesso_di_inviare_parte_dal_server(azienda, anna, servizi, google, cliente, mailoutbox):
    _casella(azienda, anna, ambiti="openid email https://www.googleapis.com/auth/gmail.readonly")     # collegata prima
    _al_cliente(cliente, anna)
    assert not google.inviati and [e for e in mailoutbox if "luca@verdi.it" in e.to]


def test_invio_spento_o_casella_da_ricollegare_parte_dal_server(azienda, anna, servizi, google, cliente, mailoutbox):
    c = _casella(azienda, anna, invio=False)
    _al_cliente(cliente, anna)
    Casella.objects.filter(pk=c.pk).update(invio=True, in_errore=True)
    _al_cliente(cliente, anna, "Secondo")
    assert not google.inviati and len([e for e in mailoutbox if "luca@verdi.it" in e.to]) == 2


def test_se_la_casella_rifiuta_parte_dal_server_e_si_segnala(azienda, anna, servizi, google, cliente, mailoutbox):
    c = _casella(azienda, anna)
    google.invio_rifiutato = True
    _al_cliente(cliente, anna)
    assert [e for e in mailoutbox if "luca@verdi.it" in e.to]
    c.refresh_from_db()
    assert c.in_errore and "partito dal server" in c.ultimo_esito


def test_microsoft_sendmail_con_il_mime(azienda, anna, servizi, microsoft, cliente, mailoutbox):
    _casella(azienda, anna, tipo="microsoft")
    _al_cliente(cliente, anna)
    inviato, = microsoft.inviati
    assert inviato["To"] == "luca@verdi.it" and IO in inviato["From"]


def test_la_copia_negli_inviati_non_si_riscrive_e_la_risposta_torna_al_record(azienda, anna, servizi, google, cliente):
    for t in ("Uno", "Due"):                                   # due aperte: di solito l'opportunità non si sceglie
        Opportunita.objects.create(azienda=azienda, titolo=t, contatto=cliente)
    trattativa = Opportunita.objects.get(titolo="Due")
    c = _casella(azienda, anna)
    m = scrivi(trattativa, anna, "Ecco il contratto.", destinatari=["luca@verdi.it"])
    m.refresh_from_db()
    adesso = timezone.now()
    copia = google.inviati[0]
    google.aggiungi("inviato1", copia, quando=adesso - timezone.timedelta(minutes=3))
    risposta = messaggio("luca@verdi.it", [IO], "Re: contratto", "Firmato, vi rimando la copia.", message_id="<risposta@verdi.it>",
                         quando=adesso - timezone.timedelta(minutes=1))
    risposta["In-Reply-To"] = m.message_id
    google.aggiungi("r1", risposta, quando=adesso - timezone.timedelta(minutes=1))
    assert "1 nuove, 1 già presenti" in sincronia.giro(c.pk)
    assert [v.corpo.splitlines()[0] for v in _storico(trattativa)] == ["Ecco il contratto.", "✉ Re: contratto"]
    assert [v.message_id for v in _storico(cliente)] == ["<risposta@verdi.it>"]
    assert not _storico(Opportunita.objects.get(titolo="Uno"))
    assert Messaggio.objects.filter(message_id=m.message_id).count() == 1
