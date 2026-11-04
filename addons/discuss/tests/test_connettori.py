import hashlib
import hmac
import json

import pytest
from django.contrib.auth.models import Permission, User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import cifratura
from core.models import Modulo
from discuss import assistente_sito, connettori, ia, sandbox, servizi
from discuss.forms import ConnessioneForm
from discuss.models import Connessione, ConversazioneEsterna, DomandaSenzaRisposta, Messaggio, Notifica, SandboxEvento, Sportello, VoceConoscenza


def _utente(nome, *altri):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_canale", "add_messaggio", *altri]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def op(db):
    return _utente("olga")


@pytest.fixture
def s(op, monkeypatch):
    monkeypatch.setattr("ai.conoscenza.embedding", lambda testi, tipo="document": None)
    x = Sportello.objects.create(nome="Assistenza", modalita=Sportello.PERSONE)
    x.operatori.add(op)
    return x


@pytest.fixture
def wa(s):
    return Connessione.objects.create(tipo="whatsapp", nome="Numero", sportello=s, id_numero="111")


@pytest.fixture
def tg(s):
    return Connessione.objects.create(tipo="telegram", nome="Bot", sportello=s)


@pytest.fixture
def modello(monkeypatch):
    stato = {"risposta": "Costa 390 euro."}
    monkeypatch.setattr(ia, "genera", lambda *a, **k: stato["risposta"])
    return stato


@pytest.fixture
def consegna_subito(monkeypatch):
    """Nei test la transazione non si chiude mai: qui la consegna parte subito, come in produzione dopo il commit."""
    monkeypatch.setattr(connettori.transaction, "on_commit", lambda f, **k: f())


def _posta_wa(c, corpo, firma=None):
    corpo = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode()
    firma = firma or "sha256=" + hmac.new(c.segreto().encode(), corpo, hashlib.sha256).hexdigest()
    return Client().post(reverse("discuss:wa_webhook", args=[c.chiave]), corpo, content_type="application/json", headers={"X-Hub-Signature-256": firma})


def _msg_wa(testo="Ciao", da="393331112222", nome="Mario Rossi", mid="wamid.1"):
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "39", "phone_number_id": "111"},
        "contacts": [{"profile": {"name": nome}, "wa_id": da}],
        "messages": [{"from": da, "id": mid, "timestamp": "1", "type": "text", "text": {"body": testo}}]}}]}]}


def _posta_tg(c, dati, segreto=None):
    return Client().post(reverse("discuss:tg_webhook", args=[c.chiave]), json.dumps(dati), content_type="application/json",
                         headers={"X-Telegram-Bot-Api-Secret-Token": segreto if segreto is not None else c.segreto()})


def _msg_tg(testo="Ciao", chat=555, update=1, tipo="private"):
    return {"update_id": update, "message": {"message_id": update, "from": {"id": chat, "is_bot": False, "first_name": "Anna", "last_name": "Bianchi"},
                                             "chat": {"id": chat, "type": tipo}, "date": 1, "text": testo}}


def test_whatsapp_verifica_firma_e_arrivo(wa, op):
    url = reverse("discuss:wa_webhook", args=[wa.chiave])
    # la verifica di Meta: risponde con la sfida solo col token giusto
    r = Client().get(url, {"hub.mode": "subscribe", "hub.verify_token": wa.verifica, "hub.challenge": "1234"})
    assert r.status_code == 200 and r.content == b"1234"
    assert Client().get(url, {"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "1"}).status_code == 403
    # firma assente o falsa: niente entra
    assert Client().post(url, json.dumps(_msg_wa()), content_type="application/json").status_code == 403
    assert _posta_wa(wa, _msg_wa(), firma="sha256=" + "0" * 64).status_code == 403
    assert not ConversazioneEsterna.objects.exists()
    # la firma copre i byte: cambiati, non vale più
    corpo = json.dumps(_msg_wa()).encode()
    firma = "sha256=" + hmac.new(wa.segreto().encode(), corpo, hashlib.sha256).hexdigest()
    assert _posta_wa(wa, corpo + b" ", firma=firma).status_code == 403
    # firma giusta: arriva agli operatori
    assert _posta_wa(wa, _msg_wa("Vorrei un preventivo")).status_code == 200
    c = ConversazioneEsterna.objects.get()
    assert c.id_esterno == "393331112222" and c.nome == "Mario Rossi" and c.canale.origine == "whatsapp" and c.connessione == wa
    assert c.canale.messaggi.get().corpo == "Vorrei un preventivo"
    assert Notifica.objects.get(utente=op).tipo == "diretto"


def test_il_messaggio_ripetuto_conta_una_volta_e_un_altro_numero_non_entra(wa):
    _posta_wa(wa, _msg_wa(mid="wamid.X"))
    _posta_wa(wa, _msg_wa(mid="wamid.X"))
    assert Messaggio.objects.count() == 1
    altro = _msg_wa(mid="wamid.Y")
    altro["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "999"
    assert _posta_wa(wa, altro).status_code == 200 and Messaggio.objects.count() == 1


def test_telegram_segreto_e_solo_chat_private(tg, op):
    assert _posta_tg(tg, _msg_tg(), segreto="").status_code == 403 and _posta_tg(tg, _msg_tg(), segreto="falso").status_code == 403
    assert not Messaggio.objects.exists()
    assert _posta_tg(tg, _msg_tg("Dal gruppo", tipo="group")).status_code == 200 and not Messaggio.objects.exists()
    bot = _msg_tg("Sono un bot", update=2)
    bot["message"]["from"]["is_bot"] = True
    _posta_tg(tg, bot)
    assert not Messaggio.objects.exists()
    _posta_tg(tg, _msg_tg("Buongiorno", update=3))
    c = ConversazioneEsterna.objects.get()
    assert c.nome == "Anna Bianchi" and c.id_esterno == "555" and c.canale.origine == "telegram"
    # stessa persona, stessa conversazione
    _posta_tg(tg, _msg_tg("Ancora io", update=4))
    assert ConversazioneEsterna.objects.count() == 1 and c.canale.messaggi.count() == 2


def test_la_risposta_dell_operatore_esce_nel_formato_giusto(wa, tg, op, monkeypatch):
    # connessioni vere: si controlla la richiesta senza uscire in rete
    Connessione.objects.filter(pk__in=[wa.pk, tg.pk]).update(sandbox=False, token_cifrato=cifratura.cifra("TOK"))
    wa.refresh_from_db()
    tg.refresh_from_db()
    fatte = []

    def post(url, **k):
        fatte.append((url, k["headers"], k["json"]))
        if "graph" in url:
            return type("R", (), {"status_code": 200, "json": lambda s: {"messages": [{"id": "wamid.OUT"}]}})()
        return type("R", (), {"status_code": 200, "json": lambda s: {"ok": True, "result": {"message_id": 77}}})()
    monkeypatch.setattr(connettori.httpx, "post", post)
    _posta_wa(wa, _msg_wa())
    _posta_tg(tg, _msg_tg())
    cw, ct = ConversazioneEsterna.objects.get(connessione=wa), ConversazioneEsterna.objects.get(connessione=tg)
    m1 = servizi.invia(cw.canale, op, "Risposta WA")
    m2 = servizi.invia(ct.canale, op, "Risposta TG")
    connettori.consegna(m1.pk)
    connettori.consegna(m2.pk)
    url, intest, corpo = fatte[0]
    assert url.startswith("https://graph.facebook.com/") and url.endswith("/111/messages") and intest["Authorization"] == "Bearer TOK"
    assert corpo["to"] == "393331112222" and corpo["text"]["body"] == "Risposta WA" and corpo["messaging_product"] == "whatsapp"
    url, _, corpo = fatte[1]
    assert url == "https://api.telegram.org/botTOK/sendMessage" and corpo == {"chat_id": "555", "text": "Risposta TG"}
    m1.refresh_from_db()
    assert m1.consegna == "inviato" and m1.id_uscita == "wamid.OUT"


def test_una_connessione_di_prova_non_esce_mai_in_rete(wa, op, monkeypatch):
    def vietato(*a, **k):
        raise AssertionError("è uscita in rete")
    monkeypatch.setattr(connettori.httpx, "post", vietato)
    _posta_wa(wa, _msg_wa())
    m = servizi.invia(ConversazioneEsterna.objects.get().canale, op, "Ciao")
    assert connettori.consegna(m.pk) == "inviato"
    e = SandboxEvento.objects.get(verso="uscita")
    assert e.testo == "Ciao" and e.richiesta["to"] == "393331112222" and e.codice == 200


def test_stati_di_consegna_e_finestra_di_24_ore(wa, op, client):
    _posta_wa(wa, _msg_wa())
    c = ConversazioneEsterna.objects.get()
    m = servizi.invia(c.canale, op, "Ciao")
    connettori.consegna(m.pk)
    m.refresh_from_db()
    # gli stati arrivano firmati e in disordine: «letto» non torna indietro
    for stato in ("read", "delivered"):
        corpo, intest = sandbox.stato_whatsapp(wa, m.id_uscita, stato, c.id_esterno)
        assert connettori.ricevi(wa, corpo, intest)[0] == 200
    m.refresh_from_db()
    assert m.consegna == "letto"
    client.force_login(op)
    assert "Letto" in client.get(reverse("discuss:messaggio", args=[m.pk])).content.decode()
    # oltre le 24 ore WhatsApp non consegna testi liberi: non ci si prova e lo si dice
    ConversazioneEsterna.objects.filter(pk=c.pk).update(ultimo_in_arrivo=timezone.now() - connettori.FINESTRA_WHATSAPP * 1.1)
    n = SandboxEvento.objects.filter(verso="uscita").count()
    tardi = servizi.invia(c.canale, op, "Troppo tardi")
    assert connettori.consegna(tardi.pk) == "fuori finestra" and SandboxEvento.objects.filter(verso="uscita").count() == n
    html = client.get(f"/discuss/c/{c.canale_id}/").content.decode()
    assert "più di 24 ore" in html and "Non inviato" in html
    # il cliente riscrive: la finestra si riapre
    _posta_wa(wa, _msg_wa("Eccomi", mid="wamid.2"))
    c.refresh_from_db()
    assert not c.fuori_finestra


def test_telegram_non_ha_la_finestra(tg, op):
    _posta_tg(tg, _msg_tg())
    c = ConversazioneEsterna.objects.get()
    ConversazioneEsterna.objects.filter(pk=c.pk).update(ultimo_in_arrivo=timezone.now() - connettori.FINESTRA_WHATSAPP * 3)
    assert connettori.consegna(servizi.invia(c.canale, op, "Dopo giorni").pk) == "inviato"


def test_errori_della_piattaforma(wa, op):
    _posta_wa(wa, _msg_wa())
    c = ConversazioneEsterna.objects.get()
    # definitivo: si mostra e non si ritenta
    Connessione.objects.filter(pk=wa.pk).update(sandbox_guasto="token")
    m = servizi.invia(c.canale, op, "A")
    assert connettori.consegna(m.pk) == "non riuscita"
    m.refresh_from_db()
    assert m.consegna == "errore" and "Token" in m.consegna_errore and Connessione.objects.get(pk=wa.pk).ultimo_errore
    # temporaneo: si rilancia così il lavoro riprova, e poi va a buon fine
    Connessione.objects.filter(pk=wa.pk).update(sandbox_guasto="limite")
    m2 = servizi.invia(c.canale, op, "B")
    with pytest.raises(connettori.ErroreConsegna):
        connettori.consegna(m2.pk)
    Connessione.objects.filter(pk=wa.pk).update(sandbox_guasto="")
    assert connettori.consegna(m2.pk) == "inviato"


def test_con_l_ai_risponde_lei_si_dichiara_e_passa_a_una_persona(s, wa, modello, op, consegna_subito):
    Sportello.objects.filter(pk=s.pk).update(modalita=Sportello.AI)
    wa.sportello.refresh_from_db()
    VoceConoscenza.objects.create(sportello=s, titolo="Prezzi", testo="Il piano costa 390 euro")
    _posta_wa(wa, _msg_wa("Quanto costa il piano?"))
    c = ConversazioneEsterna.objects.get()
    uscite = list(SandboxEvento.objects.filter(verso="uscita").values_list("testo", flat=True))
    assert "intelligenza artificiale" in uscite[0] and uscite[1] == "Costa 390 euro." and not Notifica.objects.exists()
    # chiede una persona scrivendolo
    _posta_wa(wa, _msg_wa("persona", mid="wamid.3"))
    c.refresh_from_db()
    assert c.gestita_da == "persona" and Notifica.objects.filter(utente=op, titolo__contains="ha bisogno di una persona").exists()
    # ora il messaggio va alle persone
    n = SandboxEvento.objects.filter(verso="uscita").count()
    _posta_wa(wa, _msg_wa("Ci siete?", mid="wamid.4"))
    assert SandboxEvento.objects.filter(verso="uscita").count() == n
    # non sa rispondere: la domanda resta e la chat passa
    Sportello.objects.filter(pk=s.pk).update(modalita=Sportello.AI)
    modello["risposta"] = assistente_sito.MARCATORE
    _posta_wa(wa, _msg_wa("Domanda strana", da="393339999999", mid="wamid.5"))
    assert DomandaSenzaRisposta.objects.filter(testo="Domanda strana").exists()
    assert assistente_sito.MARCATORE not in " ".join(SandboxEvento.objects.filter(verso="uscita").values_list("testo", flat=True))


def test_dopo_24_ore_di_silenzio_l_ai_riparte(s, wa, modello):
    Sportello.objects.filter(pk=s.pk).update(modalita=Sportello.AI)
    _posta_wa(wa, _msg_wa())
    c = ConversazioneEsterna.objects.get()
    ConversazioneEsterna.objects.filter(pk=c.pk).update(gestita_da="persona", risposte_ai=20, ultimo_in_arrivo=timezone.now() - connettori.FINESTRA_WHATSAPP * 1.1)
    _posta_wa(wa, _msg_wa("Sono di nuovo io", mid="wamid.9"))
    c.refresh_from_db()
    assert c.gestita_da == "ai" and ConversazioneEsterna.objects.count() == 1 and c.risposte_ai == 1


def test_contenuti_non_testuali_e_start(s, tg, wa, modello, consegna_subito):
    Sportello.objects.filter(pk=s.pk).update(modalita=Sportello.AI)
    # /start: si presenta, senza spendere una risposta del modello
    _posta_tg(tg, _msg_tg("/start"))
    c = ConversazioneEsterna.objects.get(connessione=tg)
    assert c.risposte_ai == 0 and "intelligenza artificiale" in SandboxEvento.objects.get(connessione=tg, verso="uscita").testo
    assert not c.canale.messaggi.filter(corpo="/start").exists()
    wa = Connessione.objects.get(pk=wa.pk)          # lo sportello è appena cambiato
    corpo, intest = sandbox.messaggio_cliente(wa, "393331112222", "Mario", tipo="location")
    assert connettori.ricevi(wa, corpo, intest)[0] == 200
    cw = ConversazioneEsterna.objects.get(connessione=wa)
    assert cw.canale.messaggi.filter(corpo__contains="«location»").exists()
    assert any("solo i messaggi di testo" in t for t in SandboxEvento.objects.filter(connessione=wa, verso="uscita").values_list("testo", flat=True))


def test_chiusura_saluta_e_il_messaggio_dopo_apre_una_conversazione_nuova(wa, op, client):
    _posta_wa(wa, _msg_wa())
    c = ConversazioneEsterna.objects.get()
    client.force_login(op)
    client.post(reverse("discuss:lc_chiudi", args=[c.canale_id]))
    assert any("è stata chiusa" in t for t in SandboxEvento.objects.filter(verso="uscita").values_list("testo", flat=True))
    _posta_wa(wa, _msg_wa("Torno", mid="wamid.7"))
    assert ConversazioneEsterna.objects.count() == 2


def test_testi_lunghi_si_spezzano(wa, op):
    _posta_wa(wa, _msg_wa())
    m = servizi.invia(ConversazioneEsterna.objects.get().canale, op, "x" * 5000)
    assert connettori.consegna(m.pk) == "inviato"
    assert [len(t) for t in SandboxEvento.objects.filter(verso="uscita").values_list("testo", flat=True)] == [4096, 904]


def test_sandbox_solo_per_chi_gestisce_e_solo_in_prova(client, wa):
    r = _utente("rino", "view_connessione", "change_connessione")
    url = reverse("discuss:sandbox", args=[wa.pk])
    assert client.get(url).status_code == 302
    client.force_login(_utente("ugo"))
    assert client.get(url).status_code == 403
    client.force_login(r)
    assert client.get(url).status_code == 200
    # il cliente simulato passa dal codice vero e il registro lo mostra
    j = client.post(reverse("discuss:sandbox_azione", args=[wa.pk]), {"fa": "scrivi", "testo": "Ciao", "contatto": "393330000001", "nome": "Mario"}).json()
    assert j["eventi"][0]["codice"] == 200 and j["eventi"][0]["richiesta"]["object"] == "whatsapp_business_account" and j["conversazione"]["gestita_da"] == "persona"
    # firma falsa rifiutata, ripetizione ignorata
    j = client.post(reverse("discuss:sandbox_azione", args=[wa.pk]), {"fa": "firma", "contatto": "393330000001"}).json()
    assert any(e["codice"] == 403 for e in j["eventi"])
    n = Messaggio.objects.count()
    client.post(reverse("discuss:sandbox_azione", args=[wa.pk]), {"fa": "ripeti", "contatto": "393330000001"})
    assert Messaggio.objects.count() == n + 1
    # i segreti non escono dalla pagina
    assert wa.segreto() not in client.get(url).content.decode() and wa.segreto() not in client.get(reverse("discuss:connessioni_dettaglio", args=[wa.pk])).content.decode()
    # su una connessione vera la sandbox non esiste
    Connessione.objects.filter(pk=wa.pk).update(sandbox=False)
    assert client.get(url).status_code == 404 and client.post(reverse("discuss:sandbox_azione", args=[wa.pk]), {"fa": "scrivi", "testo": "x"}).status_code == 404


def test_credenziali_cifrate_e_obbligatorie_per_una_connessione_vera(s):
    base = {"nome": "N", "sportello": s.pk, "attiva": True}
    assert ConnessioneForm({**base, "tipo": "telegram", "sandbox": True}).is_valid()
    f = ConnessioneForm({**base, "tipo": "whatsapp"})
    assert not f.is_valid() and {"nuovo_token", "nuovo_segreto", "id_numero"} <= set(f.errors)
    f = ConnessioneForm({**base, "tipo": "whatsapp", "id_numero": "1", "nuovo_token": "TOKEN-VERO", "nuovo_segreto": "SEGRETO-VERO"})
    assert f.is_valid()
    c = f.save()
    assert "TOKEN-VERO" not in c.token_cifrato and c.token() == "TOKEN-VERO" and c.segreto() == "SEGRETO-VERO"
    # vuoti: restano quelli di prima; il modulo non li rimostra
    g = ConnessioneForm({**base, "tipo": "whatsapp", "id_numero": "1"}, instance=c)
    assert g.is_valid()
    assert g.save().token() == "TOKEN-VERO" and "TOKEN-VERO" not in str(g["nuovo_token"])


def test_modulo_spento_i_webhook_non_rispondono(wa, tg):
    Modulo.objects.update_or_create(slug="discuss", defaults={"nome": "Discuss", "versione_installata": "1.7.0", "stato": "installato", "disattivato": True})
    assert _posta_wa(wa, _msg_wa()).status_code == 404 and _posta_tg(tg, _msg_tg()).status_code == 404
    assert not Messaggio.objects.exists()
    Modulo.objects.filter(slug="discuss").update(disattivato=False)
    Connessione.objects.filter(pk=wa.pk).update(attiva=False)
    assert _posta_wa(wa, _msg_wa()).status_code == 404


def test_comando_demo_crea_le_sandbox(db, monkeypatch):
    from django.core.management import call_command
    monkeypatch.setattr("ai.conoscenza.embedding", lambda testi, tipo="document": None)
    User.objects.create_superuser("capo", "c@e.it", "x")
    call_command("livechat_demo", "genera")
    assert set(Connessione.objects.values_list("tipo", "sandbox")) == {("whatsapp", True), ("telegram", True)}
    call_command("livechat_demo", "azzera")
    assert not Connessione.objects.exists()


def test_i_lavori_che_fanno_rete_non_tengono_fermo_il_database():
    """Il lavoratore mette ogni lavoro in una transazione: su SQLite, una chiamata in rete lì dentro blocca tutti gli utenti."""
    from ai import conoscenza

    from discuss import anteprime, assistente_sito, ia, livechat, modelli_wa, posta_canali  # noqa: F401
    for funzione in (conoscenza.indicizza_cron, conoscenza.indicizza_documento, anteprime.calcola, posta_canali.invia_lista, livechat.avvisa_visitatore,
                     connettori.consegna, connettori.manda_avviso, connettori.scarica_media, assistente_sito.rispondi, assistente_sito.indicizza,
                     ia.riassumi, ia.trascrivi_messaggio, ia.lavora_registrazione):
        assert getattr(funzione, "senza_transazione", False), funzione.__name__
