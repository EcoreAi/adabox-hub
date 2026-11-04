import datetime

import pytest
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.models import Lavoro, Modulo
from discuss import livechat, notifiche, presenza, servizi
from discuss.models import Canale, ConversazioneEsterna, Notifica, Sportello


def _utente(nome, *altri):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_canale", "add_canale", "add_messaggio", *altri]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def sportello(db):
    op = _utente("olga")
    s = Sportello.objects.create(nome="Assistenza", domini="www.cliente.it\nsito.it")
    s.operatori.add(op)
    return s


def _op(s):
    return s.operatori.get()


def _url(nome, s):
    return reverse(f"discuss:lc_{nome}", args=[s.chiave])


def _avvia(s, ip="1.2.3.4", **dati):
    return Client(REMOTE_ADDR=ip).post(_url("avvia", s), {"nome": "Mario Rossi", "testo": "Ho un problema", **dati})


def test_widget_e_finestra_solo_sui_siti_ammessi(client, sportello):
    r = client.get(_url("widget", sportello))
    assert r.status_code == 200 and r["Content-Type"].startswith("application/javascript") and reverse("discuss:lc_finestra", args=[sportello.chiave]) in r.content.decode()
    r = client.get(_url("finestra", sportello))
    assert r.status_code == 200 and "X-Frame-Options" not in r
    assert r["Content-Security-Policy"] == "frame-ancestors https://www.cliente.it http://www.cliente.it https://sito.it http://sito.it"
    assert "olga" not in r.content.decode()                                       # nessun nome interno
    # senza domini non la incorpora nessuno; nomi strani non finiscono nell'intestazione
    Sportello.objects.filter(pk=sportello.pk).update(domini="evil.it; script-src *\n")
    assert client.get(_url("finestra", sportello))["Content-Security-Policy"] == "frame-ancestors 'none'"
    # spento o senza operatori: non esiste
    Sportello.objects.filter(pk=sportello.pk).update(attivo=False)
    assert client.get(_url("widget", sportello)).status_code == 404
    Sportello.objects.filter(pk=sportello.pk).update(attivo=True)
    sportello.operatori.clear()
    assert client.get(_url("finestra", sportello)).status_code == 404
    assert client.get("/discuss/lc/inesistente/").status_code == 404


def test_il_visitatore_scrive_e_l_operatore_risponde(client, sportello):
    op = _op(sportello)
    r = _avvia(sportello, email="mario@esempio.it", pagina="https://www.cliente.it/prezzi")
    token = r.json()["token"]
    c = ConversazioneEsterna.objects.get(token=token)
    assert c.canale.livechat and c.canale.tipo == Canale.PRIVATO and list(c.canale.membri.all()) == [op] and c.pagina.endswith("/prezzi")
    n = Notifica.objects.get(utente=op)
    assert n.tipo == "diretto" and "Mario Rossi" in n.titolo and "Ho un problema" in n.testo
    # l'operatore la vede tra i «Clienti», col contesto e un avviso
    client.force_login(op)
    html = client.get(f"/discuss/c/{c.canale.pk}/").content.decode()
    assert '<div class="ds-gruppo-testa">Clienti</div>' in html and "Da prendere" in html and "mario@esempio.it" in html and "il visitatore legge" in html and "Mario Rossi" in html
    assert "Chiamata audio" not in html
    risposta = servizi.invia(c.canale, op, "Ciao Mario, dimmi pure")
    servizi.avviso(c.canale, op, "nota interna di sistema")
    v = Client()
    j = v.get(_url("messaggi", sportello), headers={"X-Token": token}).json()
    assert [(m["mio"], m["nome"], m["testo"]) for m in j["messaggi"]] == [(True, "Mario Rossi", "Ho un problema"), (False, "Olga", "Ciao Mario, dimmi pure")]
    assert "olga@" not in str(j) and j["chiusa"] is False
    assert v.get(_url("messaggi", sportello), {"dopo": risposta.pk}, headers={"X-Token": token}).json()["messaggi"] == []
    assert v.post(_url("scrivi", sportello), {"testo": "Grazie"}, headers={"X-Token": token}).status_code == 200
    assert c.canale.messaggi.filter(autore_esterno="Mario Rossi", corpo="Grazie").exists()
    # l'operatore chiude: il visitatore lo sa e non scrive più
    client.post(reverse("discuss:lc_chiudi", args=[c.canale.pk]))
    assert v.get(_url("messaggi", sportello), headers={"X-Token": token}).json()["chiusa"] is True
    assert v.post(_url("scrivi", sportello), {"testo": "x"}, headers={"X-Token": token}).status_code == 409


def test_un_visitatore_non_arriva_a_niente_d_altro(client, sportello):
    a = _avvia(sportello, ip="1.1.1.1").json()["token"]
    b = _avvia(sportello, ip="2.2.2.2", nome="Altro", testo="segreto di b").json()["token"]
    v = Client()
    assert "segreto" not in str(v.get(_url("messaggi", sportello), headers={"X-Token": a}).json())
    assert v.get(_url("messaggi", sportello)).status_code == 403
    assert v.get(_url("messaggi", sportello), headers={"X-Token": "falso"}).status_code == 403
    altro = Sportello.objects.create(nome="Altro")
    altro.operatori.add(_op(sportello))
    assert v.get(_url("messaggi", altro), headers={"X-Token": b}).status_code == 403   # il token vale solo per il suo sportello
    assert v.get(f"/discuss/c/{ConversazioneEsterna.objects.first().canale_id}/").status_code == 302


def test_il_testo_del_visitatore_non_e_fidato(client, sportello):
    op = _op(sportello)
    collega = _utente("carla")
    r = _avvia(sportello, testo=f"@carla @olga guarda https://erp.esempio.it/todo/attivita/1/ <script>alert(1)</script>")
    c = ConversazioneEsterna.objects.get(token=r.json()["token"])
    m = c.canale.messaggi.get()
    assert not Notifica.objects.filter(utente=collega).exists()                   # non fa suonare chi vuole
    assert not m.collegamenti.exists() and not Lavoro.objects.filter(funzione="discuss.anteprime.calcola").exists()
    client.force_login(op)
    html = client.get(f"/discuss/c/{c.canale.pk}/").content.decode()
    assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)" in html
    # un nome con markup resta testo
    r = _avvia(sportello, ip="9.9.9.9", nome="<img src=x onerror=alert(1)>")
    c2 = ConversazioneEsterna.objects.get(token=r.json()["token"])
    html = client.get(f"/discuss/c/{c2.canale.pk}/").content.decode()
    assert "<img src=x" not in html


def test_limiti_contro_gli_abusi(client, sportello, monkeypatch):
    for i in range(livechat.CHAT_PER_ORA):
        assert _avvia(sportello, ip="5.5.5.5").status_code == 200
    r = _avvia(sportello, ip="5.5.5.5")
    assert r.status_code == 429 and ConversazioneEsterna.objects.count() == livechat.CHAT_PER_ORA
    assert _avvia(sportello, ip="6.6.6.6").status_code == 200                     # un altro indirizzo non paga per il primo
    # l'indirizzo non si conserva in chiaro
    assert not ConversazioneEsterna.objects.filter(impronta_ip__contains="5.5.5.5").exists()
    # dopo un'ora si riprende
    ConversazioneEsterna.objects.update(creata=timezone.now() - datetime.timedelta(hours=2))
    assert _avvia(sportello, ip="5.5.5.5").status_code == 200
    # il campo nascosto ferma i programmi, testo e nome sono obbligatori, email controllata
    assert _avvia(sportello, ip="7.7.7.7", sito_web="spam").status_code == 400
    assert _avvia(sportello, ip="7.7.7.7", testo=" ").status_code == 422 and _avvia(sportello, ip="7.7.7.7", email="non-email").status_code == 422
    # troppi messaggi al minuto
    token = _avvia(sportello, ip="8.8.8.8").json()["token"]
    monkeypatch.setattr(livechat, "MESSAGGI_AL_MINUTO", 2)
    v = Client()
    assert v.post(_url("scrivi", sportello), {"testo": "a"}, headers={"X-Token": token}).status_code == 200
    assert v.post(_url("scrivi", sportello), {"testo": "b"}, headers={"X-Token": token}).status_code == 429


def test_il_limite_non_si_aggira_falsificando_l_indirizzo(sportello):
    url = _url("avvia", sportello)
    for i in range(livechat.CHAT_PER_ORA):
        # il primo valore lo sceglie il visitatore, l'ultimo lo aggiunge nginx
        assert Client().post(url, {"nome": "x", "testo": "y"}, headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"}).status_code == 200
    assert Client().post(url, {"nome": "x", "testo": "y"}, headers={"X-Forwarded-For": "10.9.9.9, 203.0.113.9"}).status_code == 429


def test_presenza_degli_operatori_e_risposta_per_email(client, sportello, settings):
    settings.LAVORI_SINCRONI = False
    op = _op(sportello)
    assert "nessuno online" in client.get(_url("finestra", sportello)).content.decode()
    presenza.tocca(op)
    assert "Online" in client.get(_url("finestra", sportello)).content.decode()
    c = ConversazioneEsterna.objects.get(token=_avvia(sportello, email="m@esempio.it").json()["token"])
    m = servizi.invia(c.canale, op, "Ecco la risposta")
    assert livechat.avvisa_visitatore(m.pk) == "è ancora sulla pagina" and not mail.outbox
    ConversazioneEsterna.objects.update(ultimo_visto=timezone.now() - datetime.timedelta(minutes=10))
    assert livechat.avvisa_visitatore(m.pk) == "email inviata"
    assert mail.outbox[0].to == ["m@esempio.it"] and "Ecco la risposta" in mail.outbox[0].body and "/discuss/" not in mail.outbox[0].body
    # senza email non si scrive; il messaggio più vecchio non parte se ce n'è uno nuovo
    secondo = servizi.invia(c.canale, op, "Dimenticavo")
    assert livechat.avvisa_visitatore(m.pk) == "c'è una risposta più recente" and secondo


def test_gestione_e_codice_da_incollare(client, sportello):
    respons = _utente("rino", "view_sportello", "add_sportello", "change_sportello")
    client.force_login(respons)
    html = client.get(reverse("discuss:sportelli_dettaglio", args=[sportello.pk])).content.decode()
    assert sportello.chiave in html and "widget.js" in html
    # un collega senza permesso non vede gli sportelli
    altro = Client()
    altro.force_login(_utente("ugo"))
    assert altro.get(reverse("discuss:sportelli_lista")).status_code == 403


def test_modulo_spento_la_chat_sparisce_dai_siti(sportello):
    c = ConversazioneEsterna.objects.get(token=_avvia(sportello).json()["token"])
    Modulo.objects.update_or_create(slug="discuss", defaults={"nome": "Discuss", "versione_installata": "1.5.0", "stato": "installato", "disattivato": True})
    v = Client()
    assert v.get(_url("widget", sportello)).status_code == 404 and _avvia(sportello).status_code == 404
    assert v.get(_url("messaggi", sportello), headers={"X-Token": c.token}).status_code == 404
