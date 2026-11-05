"""La chat collegata al contatto: si riconosce da solo solo il numero garantito, tutto il resto lo conferma una persona."""
import hashlib
import hmac
import json

import pytest
from django.contrib.auth.models import Permission, User
from django.test import Client
from django.urls import reverse

from contatti.models import Contatto
from core.models import Azienda, Sequenza
from discuss import clienti, servizi
from discuss.models import Connessione, ConversazioneEsterna, Iscrizione, Sportello

pytestmark = pytest.mark.django_db
NUMERO = "393331112222"


@pytest.mark.parametrize("a,b,atteso", [
    ("+39 333 1112222", NUMERO, True), ("0039-333-1112222", NUMERO, True), ("333 111 2222", NUMERO, True), ("333.1112222", "3331112222", True),
    ("333111222", NUMERO, False), ("12345", "12345", False), ("", NUMERO, False), ("3331112223", NUMERO, False), ("1112222", NUMERO, False)])
def test_stesso_numero(a, b, atteso):
    assert clienti.stesso_numero(a, b) is atteso


def _utente(nome, azienda, *permessi):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x")
    u.user_permissions.add(*Permission.objects.filter(codename__in=["view_canale", "view_contatto", *permessi]))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(monkeypatch):
    monkeypatch.setattr("ai.conoscenza.embedding", lambda testi, tipo="document": None)
    azienda = Azienda.objects.first()
    altra = Azienda.objects.create(nome="Altra")
    op = _utente("olga", azienda)
    sportello = Sportello.objects.create(nome="Assistenza", modalita=Sportello.PERSONE, azienda=azienda)
    sportello.operatori.add(op)
    wa = Connessione.objects.create(tipo="whatsapp", nome="Numero", sportello=sportello, id_numero="111")
    tg = Connessione.objects.create(tipo="telegram", nome="Bot", sportello=sportello)
    return {"az": azienda, "altra": altra, "op": op, "sportello": sportello, "wa": wa, "tg": tg}


def _arriva(c, da=NUMERO, mid="wamid.1"):
    corpo = json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "39", "phone_number_id": "111"},
        "contacts": [{"profile": {"name": "Mario"}, "wa_id": da}],
        "messages": [{"from": da, "id": mid, "timestamp": "1", "type": "text", "text": {"body": "Ciao"}}]}}]}]}).encode()
    firma = "sha256=" + hmac.new(c.segreto().encode(), corpo, hashlib.sha256).hexdigest()
    assert Client().post(reverse("discuss:wa_webhook", args=[c.chiave]), corpo, content_type="application/json",
                         headers={"X-Hub-Signature-256": firma}).status_code == 200
    return ConversazioneEsterna.objects.filter(connessione=c, id_esterno=da).order_by("-pk").first()


def _sito(s, email="", nome="Visitatore"):
    from discuss.livechat import crea_conversazione
    return crea_conversazione(s["sportello"], nome, origine="sito", usa_ai=False, email=email, impronta_ip="x")


def test_whatsapp_riconosce_un_solo_contatto_dal_numero(s):
    c = Contatto.objects.create(azienda=s["az"], nome="Rossi", cellulare="+39 333 111 2222")
    conv = _arriva(s["wa"])
    assert conv.contatto_pk == c.pk and conv.contatto_automatico


def test_due_contatti_con_lo_stesso_numero_non_si_sceglie_a_caso(s):
    a = Contatto.objects.create(azienda=s["az"], nome="Rossi", cellulare="3331112222")
    b = Contatto.objects.create(azienda=s["az"], nome="Bianchi", telefono="+393331112222")
    conv = _arriva(s["wa"])
    assert conv.contatto_pk is None
    assert {x.pk for x in clienti.candidati(conv, s["az"])} == {a.pk, b.pk}


def test_il_numero_di_un_altra_azienda_non_conta(s):
    Contatto.objects.create(azienda=s["altra"], nome="Altrui", cellulare="3331112222")
    conv = _arriva(s["wa"])
    assert conv.contatto_pk is None and clienti.candidati(conv, s["az"]) == []


def test_sportello_senza_azienda_non_riconosce_nulla(s):
    Sportello.objects.filter(pk=s["sportello"].pk).update(azienda=None)
    Contatto.objects.create(azienda=s["az"], nome="Rossi", cellulare="3331112222")
    assert _arriva(s["wa"]).contatto_pk is None


def test_l_email_del_sito_e_solo_un_suggerimento(s):
    c = Contatto.objects.create(azienda=s["az"], nome="Rossi", email="rossi@example.com")
    conv = _sito(s, email="ROSSI@example.com")
    clienti.riconosci(conv)
    assert conv.contatto_pk is None and clienti.candidati(conv, s["az"]) == [c]


def test_il_collegamento_confermato_vale_per_la_prossima_conversazione(s):
    c = Contatto.objects.create(azienda=s["az"], nome="Rossi")
    conv = _arriva(s["wa"])
    clienti.collega(conv, c)
    ConversazioneEsterna.objects.filter(pk=conv.pk).update(chiusa="2026-01-01T00:00:00Z")
    nuova = _arriva(s["wa"], mid="wamid.2")
    assert nuova.pk != conv.pk and nuova.contatto_pk == c.pk and not nuova.contatto_automatico


def test_scollegare_vale_anche_per_il_passato(s):
    c = Contatto.objects.create(azienda=s["az"], nome="Rossi")
    conv = _arriva(s["wa"])
    clienti.collega(conv, c)
    ConversazioneEsterna.objects.filter(pk=conv.pk).update(chiusa="2026-01-01T00:00:00Z")
    nuova = _arriva(s["wa"], mid="wamid.2")
    clienti.scollega(nuova)
    assert not ConversazioneEsterna.objects.filter(contatto_pk=c.pk).exists()


def test_contatto_eliminato_non_rompe_la_chat(client, s):
    c = Contatto.objects.create(azienda=s["az"], nome="Rossi", cellulare="3331112222")
    conv = _arriva(s["wa"])
    c.delete()
    client.force_login(s["op"])
    assert client.get(reverse("discuss:canale", args=[conv.canale_id])).status_code == 200


def _url(nome, conv):
    return reverse(f"discuss:{nome}", args=[conv.canale_id])


def test_nella_chat_si_vede_la_scheda_del_cliente(client, s):
    Contatto.objects.create(azienda=s["az"], nome="Rossi Srl", cellulare="3331112222")
    conv = _arriva(s["wa"])
    client.force_login(s["op"])
    pagina = client.get(_url("canale", conv)).content.decode()
    assert "Riconosciuto dal numero" in pagina and "Rossi Srl" in pagina


def test_senza_permesso_sui_contatti_niente_scheda_ne_azioni(client, s):
    c = Contatto.objects.create(azienda=s["az"], nome="Rossi Srl", cellulare="3331112222")
    conv = _arriva(s["wa"])
    u = User.objects.create_user("solochat", "s@example.com", "x")
    u.user_permissions.add(*Permission.objects.filter(codename="view_canale"))
    u.profilo.aziende.set([s["az"]])
    servizi.iscrivi(conv.canale, u, 0, ruolo=Iscrizione.MODERATORE)
    client.force_login(u)
    assert "Rossi Srl" not in client.get(_url("canale", conv)).content.decode()
    assert client.post(_url("lc_cliente_collega", conv), {"contatto": c.pk}).status_code == 403


def test_chi_non_e_nella_chat_non_collega(client, s):
    c = Contatto.objects.create(azienda=s["az"], nome="Rossi")
    conv = _arriva(s["wa"])
    client.force_login(_utente("estraneo", s["az"]))
    assert client.post(_url("lc_cliente_collega", conv), {"contatto": c.pk}).status_code == 404
    assert client.get(_url("lc_cliente_cerca", conv), {"q": "Rossi"}).status_code == 404


def test_cerca_e_collega_solo_nell_azienda_corrente(client, s):
    Contatto.objects.create(azienda=s["az"], nome="Rossi Nostro")
    altrui = Contatto.objects.create(azienda=s["altra"], nome="Rossi Altrui")
    conv = _arriva(s["wa"])
    client.force_login(s["op"])
    risultati = client.get(_url("lc_cliente_cerca", conv), {"q": "Rossi"}).content.decode()
    assert "Rossi Nostro" in risultati and "Rossi Altrui" not in risultati
    assert client.post(_url("lc_cliente_collega", conv), {"contatto": altrui.pk}).status_code == 404
    conv.refresh_from_db()
    assert conv.contatto_pk is None


def test_operatore_in_un_altra_azienda_non_collega(client, s):
    c = Contatto.objects.create(azienda=s["altra"], nome="Altrui")
    conv = _arriva(s["wa"])
    u = _utente("altrove", s["altra"])
    servizi.iscrivi(conv.canale, u, 0, ruolo=Iscrizione.MODERATORE)
    client.force_login(u)
    assert client.post(_url("lc_cliente_collega", conv), {"contatto": c.pk}).status_code == 403


def test_collega_e_scollega_dalla_pagina(client, s):
    c = Contatto.objects.create(azienda=s["az"], nome="Rossi")
    conv = _arriva(s["wa"])
    client.force_login(s["op"])
    assert client.post(_url("lc_cliente_collega", conv), {"contatto": c.pk}).status_code == 302
    conv.refresh_from_db()
    assert conv.contatto_pk == c.pk and not conv.contatto_automatico
    assert client.post(_url("lc_cliente_scollega", conv)).status_code == 302
    conv.refresh_from_db()
    assert conv.contatto_pk is None


def test_crea_il_contatto_dalla_chat(client, s):
    Sequenza.objects.create(codice="contatti.contatto", azienda=s["az"], formato="C{numero:05d}")
    conv = _arriva(s["wa"])
    client.force_login(s["op"])
    assert client.post(_url("lc_cliente_crea", conv)).status_code == 403
    s["op"].user_permissions.add(Permission.objects.get(codename="add_contatto"))
    client.force_login(User.objects.get(pk=s["op"].pk))
    assert client.post(_url("lc_cliente_crea", conv)).status_code == 302
    conv.refresh_from_db()
    c = Contatto.objects.get(pk=conv.contatto_pk)
    assert c.azienda == s["az"] and c.cellulare == f"+{NUMERO}" and c.nome == "Mario" and c.codice


def test_sul_contatto_si_vedono_solo_le_chat_di_cui_si_fa_parte(client, s):
    c = Contatto.objects.create(azienda=s["az"], nome="Rossi", cellulare="3331112222")
    conv = _arriva(s["wa"])
    url = f"/contatti/contatti/{c.pk}/"
    client.force_login(s["op"])
    assert reverse("discuss:canale", args=[conv.canale_id]) in client.get(url).content.decode()
    client.force_login(_utente("estraneo", s["az"]))
    assert reverse("discuss:canale", args=[conv.canale_id]) not in client.get(url).content.decode()
