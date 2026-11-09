"""Pagamenti online: Stripe Checkout (simulato con un trasporto HTTP finto), conferma una volta sola al ritorno o dal
webhook firmato, nessun doppio incasso, solo fatture del cliente, link firmato per le email, chiavi cifrate."""
import datetime
import hashlib
import hmac
import json
import time
from decimal import Decimal

import httpx2 as httpx
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from contatti.models import Contatto
from core import cifratura
from core.models import Azienda
from fatturazione.models import Fattura, Incasso, Scadenza
from pagamenti import fornitori, servizi
from pagamenti.models import FornitorePagamento, Pagamento


@pytest.fixture
def s(db, settings):
    settings.SITO_URL = "https://hub.esempio.it"
    azienda = Azienda.objects.get(pk=1)
    rossi = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    return {"azienda": azienda, "rossi": rossi}


def _fattura(s, cliente=None, residuo="122.00", numero="FT/1"):
    f = Fattura.objects.create(azienda=s["azienda"], cliente=cliente or s["rossi"], numero=numero)
    Fattura.objects.filter(pk=f.pk).update(stato=Fattura.EMESSA, totale=Decimal("122.00"))
    Scadenza.objects.create(fattura=f, data=datetime.date(2026, 12, 31), importo=Decimal(residuo))
    return Fattura.objects.get(pk=f.pk)


def _stripe(s, **extra):
    return FornitorePagamento.objects.create(azienda=s["azienda"], tipo="stripe", chiave_cifrata=cifratura.cifra("sk_test_123"),
                                             segreto_webhook_cifrato=cifratura.cifra("whsec_abc"), **extra)


class FintoStripe:
    def __init__(self, pagato=True):
        self.richieste, self.pagato = [], pagato

    def __call__(self, r):
        self.richieste.append(r)
        if r.method == "POST" and r.url.path == "/v1/checkout/sessions":
            return httpx.Response(200, json={"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"})
        if r.url.path == "/v1/checkout/sessions/cs_test_1":
            return httpx.Response(200, json={"id": "cs_test_1", "payment_status": "paid" if self.pagato else "unpaid", "payment_intent": "pi_42"})
        return httpx.Response(404, json={"error": {"message": "sconosciuto"}})


@pytest.fixture
def stripe(monkeypatch):
    finto = FintoStripe()
    monkeypatch.setattr(fornitori, "HTTP", httpx.Client(transport=httpx.MockTransport(lambda r: finto(r))))
    return finto


def test_sessione_stripe_e_conferma_al_ritorno(client, s, stripe):
    _stripe(s)
    f = _fattura(s)
    p = servizi.avvia(f)
    corpo = dict(x.split("=", 1) for x in stripe.richieste[0].content.decode().split("&"))
    assert corpo["line_items%5B0%5D%5Bprice_data%5D%5Bunit_amount%5D"] == "12200" and corpo["mode"] == "payment"
    assert stripe.richieste[0].headers["idempotency-key"] == f"adabox-pagamento-{p.pk}" and stripe.richieste[0].headers["authorization"] == "Bearer sk_test_123"
    assert p.url_pagamento.startswith("https://checkout.stripe.com/") and p.id_esterno == "cs_test_1"
    ritorno = corpo["success_url"].replace("%3A", ":").replace("%2F", "/").replace("https://hub.esempio.it", "")
    pagina = client.get(ritorno).content.decode()
    assert "Pagamento ricevuto" in pagina
    client.get(ritorno)                                                                  # di nuovo: nessun doppio incasso
    f.refresh_from_db()
    incassi = Incasso.objects.filter(scadenza__fattura=f)
    assert f.residuo == 0 and incassi.count() == 1 and incassi.get().metodo == "carta" and "pi_42" in incassi.get().riferimento


def test_non_pagato_resta_in_verifica(client, s, stripe):
    stripe.pagato = False
    _stripe(s)
    p = servizi.avvia(_fattura(s))
    assert servizi.verifica(p).stato == Pagamento.AVVIATO and not Incasso.objects.exists()


def _firma(corpo, segreto="whsec_abc", istante=None):
    istante = istante or int(time.time())
    return f"t={istante},v1={hmac.new(segreto.encode(), f'{istante}.'.encode() + corpo, hashlib.sha256).hexdigest()}"


def test_webhook_firmato(client, s, stripe):
    fornitore = _stripe(s)
    p = servizi.avvia(_fattura(s))
    evento = json.dumps({"type": "checkout.session.completed", "data": {"object": {"id": "cs_test_1", "payment_status": "paid", "payment_intent": "pi_7"}}}).encode()
    url = reverse("pagamenti:webhook", args=[fornitore.pk])
    assert client.post(url, evento, content_type="application/json", HTTP_STRIPE_SIGNATURE=_firma(evento, "sbagliato")).status_code == 400
    assert client.post(url, evento, content_type="application/json", HTTP_STRIPE_SIGNATURE=_firma(evento, istante=int(time.time()) - 3600)).status_code == 400
    assert not Incasso.objects.exists()
    assert client.post(url, evento, content_type="application/json", HTTP_STRIPE_SIGNATURE=_firma(evento)).status_code == 200
    p.refresh_from_db()
    assert p.stato == Pagamento.PAGATO and p.riferimento == "pi_7" and Incasso.objects.count() == 1
    client.post(url, evento, content_type="application/json", HTTP_STRIPE_SIGNATURE=_firma(evento))
    assert Incasso.objects.count() == 1                                                  # Stripe ripete gli eventi: un incasso solo


def test_gia_incassata_nel_frattempo(s, stripe):
    from fatturazione import operazioni
    _stripe(s)
    f = _fattura(s)
    p = servizi.avvia(f)
    operazioni.incassa_fattura(f, Decimal("100.00"))                                      # bonifico arrivato mentre pagava
    p = servizi.verifica(p)
    f.refresh_from_db()
    assert p.stato == Pagamento.PAGATO and "da rimborsare" in p.nota and f.residuo == 0
    assert not servizi.pagabile(f)
    with pytest.raises(fornitori.ErrorePagamento):
        servizi.avvia(f)


def test_dal_portale_con_il_fornitore_simulato(client, s):
    from portale.inviti import invita
    FornitorePagamento.objects.create(azienda=s["azienda"], tipo="finto", nome="Prova")
    mia = _fattura(s)
    bianchi = Contatto.objects.create(azienda=s["azienda"], nome="Bianchi Spa", cliente=True)
    altrui = _fattura(s, cliente=bianchi, numero="FT/2")
    anna = Contatto.objects.create(azienda=s["azienda"], nome="Anna", tipo="persona", societa=s["rossi"], email="anna@rossi.it")
    client.force_login(invita(anna, User.objects.create_superuser("sara", "s@x.it", "x")).utente)
    pagina = client.get(reverse("fatturazione:portale_fatture")).content.decode()
    assert "Paga ora" in pagina and reverse("pagamenti:paga_portale", args=[mia.pk]) in pagina
    assert client.post(reverse("pagamenti:paga_portale", args=[altrui.pk])).status_code == 404
    r = client.post(reverse("pagamenti:paga_portale", args=[mia.pk]))
    p = Pagamento.objects.get()
    assert r.url == reverse("pagamenti:finto", args=[p.pk])
    r = client.post(r.url, {"azione": "paga"})
    assert "Pagamento ricevuto" in client.get(r.url).content.decode()
    mia.refresh_from_db()
    assert mia.residuo == 0 and "Paga ora" not in client.get(reverse("fatturazione:portale_fatture")).content.decode()


def test_link_firmato_per_le_email(client, s):
    FornitorePagamento.objects.create(azienda=s["azienda"], tipo="finto")
    f = _fattura(s)
    link = servizi.link(f).replace("https://hub.esempio.it", "")
    pagina = client.get(link).content.decode()
    assert "Paga ora" in pagina and "122,00" in pagina or "122.00" in pagina
    assert client.get(link[:-3] + "xyz/").status_code == 400
    r = client.post(link)
    assert r.status_code == 302 and "/pagamenti/simulato/" in r.url


def test_form_del_fornitore_e_chiavi_cifrate(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    r = client.post(reverse("pagamenti:fornitori_nuovo"), {"nome": "Stripe", "tipo": "stripe", "attivo": "on", "nuova_chiave": "pk_test_sbagliata"})
    assert r.status_code == 200 and not FornitorePagamento.objects.exists()
    client.post(reverse("pagamenti:fornitori_nuovo"), {"nome": "Stripe", "tipo": "stripe", "attivo": "on", "nuova_chiave": "sk_test_segreta", "nuovo_segreto": "whsec_x"})
    f = FornitorePagamento.objects.get()
    assert f.chiave() == "sk_test_segreta" and f.segreto_webhook() == "whsec_x" and f.di_prova
    elenco = client.get(reverse("pagamenti:fornitori_lista")).content.decode()
    assert "sk_test_segreta" not in elenco and "(prova)" in elenco
    assert "checkout.session.completed" in client.get(reverse("pagamenti:fornitori_dettaglio", args=[f.pk])).content.decode()


class FintoPayPal:
    """Il server PayPal finto: token, ordine, cattura e verifica dei webhook."""
    def __init__(self, firma_valida=True):
        self.richieste, self.firma_valida, self.stato = [], firma_valida, "CREATED"

    def __call__(self, r):
        self.richieste.append(r)
        percorso = r.url.path
        if percorso == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "A21AA", "expires_in": 32400})
        if r.method == "POST" and percorso == "/v2/checkout/orders":
            return httpx.Response(201, json={"id": "ORD1", "status": "PAYER_ACTION_REQUIRED",
                                             "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORD1"}]})
        if r.method == "GET" and percorso == "/v2/checkout/orders/ORD1":
            return httpx.Response(200, json={"id": "ORD1", "status": self.stato})
        if r.method == "POST" and percorso == "/v2/checkout/orders/ORD1/capture":
            self.stato = "COMPLETED"
            return httpx.Response(201, json={"id": "ORD1", "status": "COMPLETED", "purchase_units": [
                {"payments": {"captures": [{"id": "CAP9", "status": "COMPLETED"}]}}]})
        if percorso == "/v1/notifications/verify-webhook-signature":
            return httpx.Response(200, json={"verification_status": "SUCCESS" if self.firma_valida else "FAILURE"})
        return httpx.Response(404, json={"message": "sconosciuto"})


@pytest.fixture
def paypal(monkeypatch):
    finto = FintoPayPal()
    monkeypatch.setattr(fornitori, "HTTP", httpx.Client(transport=httpx.MockTransport(lambda r: finto(r))))
    return finto


def _paypal(s):
    return FornitorePagamento.objects.create(azienda=s["azienda"], nome="PayPal", tipo="paypal", client_id="AbCdClient", sandbox=True,
                                             chiave_cifrata=cifratura.cifra("EFsegreto"), segreto_webhook_cifrato=cifratura.cifra("WH-123"))


def test_paypal_ordine_cattura_al_ritorno(client, s, paypal):
    _paypal(s)
    f = _fattura(s)
    p = servizi.avvia(f)
    ordine = json.loads(next(r for r in paypal.richieste if r.url.path == "/v2/checkout/orders").content)
    assert all(r.url.host == "api-m.sandbox.paypal.com" for r in paypal.richieste)
    assert ordine["purchase_units"][0]["amount"] == {"currency_code": "EUR", "value": "122.00"}
    assert p.id_esterno == "ORD1" and p.url_pagamento.startswith("https://www.sandbox.paypal.com/")
    ritorno = ordine["payment_source"]["paypal"]["experience_context"]["return_url"].replace("https://hub.esempio.it", "")
    paypal.stato = "APPROVED"                                              # il cliente ha approvato su PayPal
    assert "Pagamento ricevuto" in client.get(ritorno).content.decode()
    client.get(ritorno)                                                     # di nuovo: niente seconda cattura né incasso
    assert sum(r.url.path.endswith("/capture") for r in paypal.richieste) == 1
    f.refresh_from_db()
    incasso = Incasso.objects.get(scadenza__fattura=f)
    assert f.residuo == 0 and "CAP9" in incasso.riferimento and Pagamento.objects.get().riferimento == "CAP9"


def test_paypal_webhook_verificato(client, s, paypal):
    fornitore = _paypal(s)
    f = _fattura(s)
    servizi.avvia(f)
    paypal.stato = "APPROVED"
    evento = {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "ORD1"}}
    url = reverse("pagamenti:webhook", args=[fornitore.pk])
    paypal.firma_valida = False
    assert client.post(url, json.dumps(evento), content_type="application/json").status_code == 400
    assert Pagamento.objects.get().stato == Pagamento.AVVIATO
    paypal.firma_valida = True
    r = client.post(url, json.dumps(evento), content_type="application/json", headers={"Paypal-Transmission-Id": "t1"})
    assert r.status_code == 200 and Pagamento.objects.get().stato == Pagamento.PAGATO
    verifica = json.loads([r for r in paypal.richieste if r.url.path.endswith("verify-webhook-signature")][-1].content)
    assert verifica["webhook_id"] == "WH-123" and verifica["transmission_id"] == "t1"
    evento = {"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "CAP9", "supplementary_data": {"related_ids": {"order_id": "ORD1"}}}}
    assert client.post(url, json.dumps(evento), content_type="application/json").status_code == 200
    assert Incasso.objects.filter(scadenza__fattura=f).count() == 1


def test_paypal_form(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    r = client.post(reverse("pagamenti:fornitori_nuovo"), {"nome": "PayPal", "tipo": "paypal", "attivo": "on", "nuova_chiave": "EFsegreto"})
    assert r.status_code == 200 and not FornitorePagamento.objects.exists()           # manca il Client ID
    client.post(reverse("pagamenti:fornitori_nuovo"), {"nome": "PayPal", "tipo": "paypal", "client_id": "AbCdClient", "sandbox": "on",
                                                       "attivo": "on", "nuova_chiave": "EFsegreto", "nuovo_segreto": "WH-123"})
    f = FornitorePagamento.objects.get()
    assert f.chiave() == "EFsegreto" and f.di_prova and "(sandbox)" in client.get(reverse("pagamenti:fornitori_lista")).content.decode()
    assert "Payment capture completed" in client.get(reverse("pagamenti:fornitori_dettaglio", args=[f.pk])).content.decode()


def test_link_nelle_email_della_fattura(s):
    from fatturazione import operazioni
    f = _fattura(s)
    assert operazioni.frase_pagamento(f) == ""                                           # nessun fornitore: niente link
    FornitorePagamento.objects.create(azienda=s["azienda"], tipo="finto")
    assert operazioni.frase_pagamento(f).startswith("\nPuò pagarla online da questo link: https://hub.esempio.it/")
    from automazioni import catalogo
    assert catalogo.domini()["fattura"].valori(f)["link_pagamento"].startswith("https://hub.esempio.it/pagamenti/fattura/")
