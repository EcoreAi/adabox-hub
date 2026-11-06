import pytest
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import cifratura
from discuss import connettori, modelli_wa, sandbox
from discuss.models import Connessione, ConversazioneEsterna, ModelloWhatsApp, SandboxEvento, Sportello


def _utente(nome, *altri):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_canale", "add_messaggio", *altri]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def op(db):
    return _utente("olga")


@pytest.fixture
def wa(op):
    s = Sportello.objects.create(nome="Assistenza")
    s.operatori.add(op)
    return Connessione.objects.create(tipo="whatsapp", nome="N", sportello=s, id_numero="111")


@pytest.fixture
def conv(wa):
    corpo, intest = sandbox.messaggio_cliente(wa, "393331", "Mario", "Ciao")
    connettori.ricevi(wa, corpo, intest)
    c = ConversazioneEsterna.objects.get()
    ConversazioneEsterna.objects.filter(pk=c.pk).update(ultimo_in_arrivo=timezone.now() - connettori.FINESTRA_WHATSAPP * 2)
    c.refresh_from_db()
    return c


@pytest.fixture
def modello(wa):
    return ModelloWhatsApp.objects.create(connessione=wa, nome="ripresa", corpo="Ciao {{1}}, la tua pratica {{2}} è pronta.", stato=ModelloWhatsApp.APPROVATO)


def test_fuori_finestra_si_propone_il_modello_e_parte(client, op, conv, modello, settings):
    settings.LAVORI_SINCRONI = False
    client.force_login(op)
    html = client.get(f"/discuss/c/{conv.canale_id}/").content.decode()
    url = reverse("discuss:wa_modello", args=[conv.canale_id])
    assert "Manda un modello" in html and url in html
    f = client.get(url).content.decode()
    assert "ripresa" in f and 'name="v2"' in f and 'value="Mario"' in f
    r = client.post(url, {"modello": modello.pk, "v1": "Mario", "v2": "A-7"})
    assert r.status_code == 302
    m = conv.canale.messaggi.order_by("-pk").first()
    assert m.corpo == "Ciao Mario, la tua pratica A-7 è pronta." and m.dati_modello["nome"] == "ripresa" and m.autore == op
    assert connettori.consegna(m.pk) == "inviato"                                  # il testo libero qui non partirebbe
    e = SandboxEvento.objects.filter(verso="uscita").last()
    assert e.richiesta["type"] == "template" and e.richiesta["template"]["name"] == "ripresa" and e.richiesta["to"] == "393331"
    assert e.richiesta["template"]["components"][0]["parameters"] == [{"type": "text", "text": "Mario"}, {"type": "text", "text": "A-7"}]
    assert "pratica A-7" in e.testo


def test_solo_modelli_approvati_e_valori_che_whatsapp_accetta(client, op, conv, modello, wa, settings):
    settings.LAVORI_SINCRONI = False
    client.force_login(op)
    url = reverse("discuss:wa_modello", args=[conv.canale_id])
    n = conv.canale.messaggi.count()
    attesa = ModelloWhatsApp.objects.create(connessione=wa, nome="nuovo", corpo="Ciao")
    assert "nuovo" not in client.get(url).content.decode()
    client.post(url, {"modello": attesa.pk})
    for valori in ({"v1": "Mario"}, {"v1": "a\nb", "v2": "x"}, {"v1": "a     b", "v2": "x"}, {"v1": " ", "v2": "x"}, {"v1": "x" * 201, "v2": "y"}):
        client.post(url, {"modello": modello.pk, **valori})
    assert conv.canale.messaggi.count() == n


def test_la_piattaforma_rifiuta_un_modello_ritirato(op, conv, modello):
    m = modelli_wa.manda(conv, op, modello, ["Mario", "A"])
    ModelloWhatsApp.objects.filter(pk=modello.pk).update(stato=ModelloWhatsApp.RIFIUTATO)
    assert connettori.consegna(m.pk) == "non riuscita"
    m.refresh_from_db()
    assert m.consegna == "errore" and "non è approvato" in m.consegna_errore


def test_chi_non_c_entra_non_manda(conv, modello):
    altro = Client()
    altro.force_login(_utente("ugo"))
    assert altro.get(reverse("discuss:wa_modello", args=[conv.canale_id])).status_code == 404
    assert altro.post(reverse("discuss:wa_modello", args=[conv.canale_id]), {"modello": modello.pk, "v1": "a", "v2": "b"}).status_code == 404


def test_telegram_non_ha_modelli(client, op):
    s = Sportello.objects.create(nome="T")
    s.operatori.add(op)
    tg = Connessione.objects.create(tipo="telegram", nome="B", sportello=s)
    corpo, intest = sandbox.messaggio_cliente(tg, "5", "Mario", "Ciao")
    connettori.ricevi(tg, corpo, intest)
    client.force_login(op)
    assert client.get(reverse("discuss:wa_modello", args=[ConversazioneEsterna.objects.get().canale_id])).status_code == 404


def test_il_nome_e_le_variabili_si_controllano(wa):
    with pytest.raises(ValidationError):
        ModelloWhatsApp(connessione=wa, nome="Con Spazi", corpo="x").full_clean()
    with pytest.raises(ValidationError):
        ModelloWhatsApp(connessione=wa, nome="salto", corpo="{{1}} e {{3}}").full_clean()
    ModelloWhatsApp(connessione=wa, nome="giusto", corpo="{{1}} e {{2}}").full_clean()


def test_sandbox_fa_le_veci_di_meta(client, wa):
    r = _utente("rino", "view_connessione", "change_connessione")
    client.force_login(r)
    m = ModelloWhatsApp.objects.create(connessione=wa, nome="prova", corpo="x")
    assert "prova" in client.get(reverse("discuss:sandbox", args=[wa.pk])).content.decode()
    client.post(reverse("discuss:sandbox_azione", args=[wa.pk]), {"fa": "meta", "esito": "approva", "modello": m.pk})
    m.refresh_from_db()
    assert m.stato == "approvato"
    client.post(reverse("discuss:sandbox_azione", args=[wa.pk]), {"fa": "meta", "esito": "rifiuta", "modello": m.pk})
    m.refresh_from_db()
    assert m.stato == "rifiutato" and m.motivo


def test_con_meta_vera_invio_e_stato(wa, monkeypatch):
    Connessione.objects.filter(pk=wa.pk).update(sandbox=False, id_account="WABA1", token_cifrato=cifratura.cifra("TOK"))
    wa.refresh_from_db()
    m = ModelloWhatsApp.objects.create(connessione=wa, nome="prova", corpo="Ciao {{1}}")
    fatte = []
    monkeypatch.setattr(modelli_wa.httpx, "post", lambda url, **k: fatte.append((url, k)) or type("R", (), {"status_code": 200, "json": lambda s: {"id": "1"}})())
    modelli_wa.a_meta(m)
    url, k = fatte[0]
    assert url.endswith("/WABA1/message_templates") and k["headers"]["Authorization"] == "Bearer TOK" and k["json"]["components"][0]["example"]["body_text"] == [["esempio 1"]]
    monkeypatch.setattr(modelli_wa.httpx, "get", lambda url, **k: type("R", (), {"status_code": 200, "json": lambda s: {"data": [
        {"name": "prova", "language": "it", "status": "REJECTED", "rejected_reason": "PROMOTIONAL"}, {"name": "altro", "language": "it", "status": "APPROVED"}]}})())
    assert modelli_wa.sincronizza(wa) == 1
    m.refresh_from_db()
    assert m.stato == "rifiutato" and m.motivo == "PROMOTIONAL"
    # senza account o con Meta giù: lo si dice, e il lavoro pianificato non si ferma
    Connessione.objects.filter(pk=wa.pk).update(id_account="")
    wa.refresh_from_db()
    with pytest.raises(connettori.ErroreConsegna):
        modelli_wa.a_meta(m)
    assert modelli_wa.sincronizza_tutti() == "modelli aggiornati: 0"


def test_una_connessione_di_prova_non_chiama_meta(wa, monkeypatch):
    def vietato(*a, **k):
        raise AssertionError("è uscita in rete")
    monkeypatch.setattr(modelli_wa.httpx, "post", vietato)
    monkeypatch.setattr(modelli_wa.httpx, "get", vietato)
    m = ModelloWhatsApp.objects.create(connessione=wa, nome="prova", corpo="x")
    modelli_wa.a_meta(m)
    assert modelli_wa.sincronizza(wa) == 0
