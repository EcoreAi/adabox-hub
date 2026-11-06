"""Il preventivo online: chi ha il link risponde una volta, solo al documento che ha letto e finché vale."""
import datetime
import re
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

import fiscale
from contatti.models import Contatto
from core.models import Azienda, Messaggio
from fiscale.models import AliquotaIva
from vendite import lavori, operazioni
from vendite.models import OrdineVendita, RigaVendita
from vendite.segnali import ordine_confermato


@pytest.fixture
def ordine(db):
    call_command("loaddata", str(Path(fiscale.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, email="rossi@example.com")
    capo = User.objects.create_user("capo", "capo@example.com", "x")
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente, numero="PV/1", stato=OrdineVendita.INVIATO, commerciale=capo)
    RigaVendita.objects.create(ordine=o, descrizione="Sviluppo <b>sito</b>", prezzo=D(1000), aliquota=AliquotaIva.objects.get(codice="22"))
    o.ricalcola()
    return o


def _url(o):
    return operazioni.link(o).split("://", 1)[1].split("/", 1)[1].join(["/", ""])


def test_il_link_mostra_il_documento_senza_accesso_e_con_escape(client, ordine):
    pagina = client.get(_url(ordine)).content.decode()
    assert "PV/1" in pagina and "Accetto il preventivo" in pagina
    assert "Sviluppo &lt;b&gt;sito&lt;/b&gt;" in pagina and "<b>sito</b>" not in pagina


def test_accettazione_conferma_una_volta_e_lascia_traccia(client, ordine):
    url = _url(ordine)
    segnali = []
    ricevi = lambda **k: segnali.append(k)      # noqa: E731
    ordine_confermato.connect(ricevi)
    try:
        r = client.post(url, {"azione": "accetta", "nome": "Mario Rossi", "conferma": "1"}, REMOTE_ADDR="203.0.113.9")
        assert r.status_code == 200 and "Grazie, Mario Rossi" in r.content.decode()
        client.post(url, {"azione": "accetta", "nome": "Altro", "conferma": "1"})
    finally:
        ordine_confermato.disconnect(ricevi)
    ordine.refresh_from_db()
    assert ordine.stato == OrdineVendita.CONFERMATO and ordine.numero_ordine and ordine.risposta_nome == "Mario Rossi"
    assert ordine.risposta_ip == "203.0.113.9" and ordine.risposta_impronta == operazioni.impronta(ordine)
    assert len(segnali) == 1
    assert {tuple(m.to) for m in mail.outbox} == {("capo@example.com",), ("rossi@example.com",)}
    assert Messaggio.objects.filter(object_id=ordine.pk, corpo__contains="accettato online").exists()


@pytest.mark.parametrize("dati", [{"azione": "accetta", "nome": "Mario"}, {"azione": "accetta", "nome": " ", "conferma": "1"}])
def test_servono_nome_e_conferma(client, ordine, dati):
    assert client.post(_url(ordine), dati).status_code == 400
    ordine.refresh_from_db()
    assert ordine.stato == OrdineVendita.INVIATO and not ordine.risposta


def test_rifiuto_non_conferma_e_avvisa(client, ordine):
    client.post(_url(ordine), {"azione": "rifiuta", "motivo": "Troppo caro"})
    ordine.refresh_from_db()
    assert ordine.stato == OrdineVendita.INVIATO and ordine.risposta == OrdineVendita.RIFIUTATO and ordine.risposta_motivo == "Troppo caro"
    assert [m.to for m in mail.outbox] == [["capo@example.com"]] and "Troppo caro" in mail.outbox[0].body


def test_modificato_dopo_l_invio_il_vecchio_link_non_vale(client, ordine):
    url = _url(ordine)
    riga = ordine.righe.get()
    riga.prezzo = D(2000)
    riga.save()
    ordine.ricalcola()
    pagina = client.get(url).content.decode()
    assert "è stato aggiornato" in pagina and "2.440" not in pagina and "2440" not in pagina
    client.post(url, {"azione": "accetta", "nome": "Mario Rossi", "conferma": "1"})
    ordine.refresh_from_db()
    assert ordine.stato == OrdineVendita.INVIATO


def test_scaduto(client, ordine):
    ordine.validita = timezone.localdate() - datetime.timedelta(days=1)
    ordine.save()
    assert "è scaduto" in client.get(_url(ordine)).content.decode()
    client.post(_url(ordine), {"azione": "accetta", "nome": "Mario Rossi", "conferma": "1"})
    ordine.refresh_from_db()
    assert ordine.stato == OrdineVendita.INVIATO


def test_senza_validita_il_link_scade_dopo_90_giorni(client, ordine):
    url = _url(ordine)
    with mock.patch("django.utils.timezone.localdate", return_value=timezone.localdate() + datetime.timedelta(days=91)):
        assert "è scaduto" in client.get(url).content.decode()


def test_link_alterato_o_preventivo_non_inviato(client, ordine):
    url = _url(ordine)
    assert client.get(url[:-3] + "xx/").status_code == 400
    OrdineVendita.objects.filter(pk=ordine.pk).update(stato=OrdineVendita.BOZZA)
    pagina = client.get(url).content.decode()
    assert "non è più aperto" in pagina and "Accetto il preventivo" not in pagina


def test_l_email_del_preventivo_contiene_il_link(ordine, client):
    lavori.invia(ordine.pk)
    corpo = mail.outbox[-1].body
    link = re.search(r"https?://\S+/vendite/preventivo/\S+", corpo).group(0)
    percorso = "/" + link.split("://", 1)[1].split("/", 1)[1]
    assert client.get(percorso).status_code == 200
