"""I fornitori di pagamento: Stripe (Checkout), PayPal (Orders v2), entrambi via API REST senza librerie, e uno simulato
per prove e demo. Ogni fornitore sa creare la pagina di pagamento, dire se è stata pagata e verificare i suoi webhook."""
import hashlib
import hmac
import json
import time

import httpx2 as httpx
from django.urls import reverse

API = "https://api.stripe.com/v1"
PAYPAL = "https://api-m.paypal.com"
PAYPAL_SANDBOX = "https://api-m.sandbox.paypal.com"
TOLLERANZA_WEBHOOK = 300                                 # secondi: una firma più vecchia non vale (replay)
HTTP = None                                              # solo per i test: un client httpx finto


class ErrorePagamento(RuntimeError):
    pass


def _client():
    return HTTP or httpx.Client(timeout=30, trust_env=False)


def _stripe(fornitore, metodo, percorso, dati=None, idempotenza=""):
    intestazioni = {"Authorization": f"Bearer {fornitore.chiave()}"}
    if idempotenza:
        intestazioni["Idempotency-Key"] = idempotenza
    client = _client()
    try:
        r = client.request(metodo, f"{API}{percorso}", data=dati, headers=intestazioni)
    except httpx.HTTPError as e:
        raise ErrorePagamento(f"Stripe non risponde: {type(e).__name__}") from e
    finally:
        if HTTP is None:
            client.close()
    try:
        corpo = r.json()
    except ValueError as e:
        raise ErrorePagamento(f"Stripe ha risposto in modo illeggibile (HTTP {r.status_code})") from e
    if r.status_code >= 400:
        messaggio = (corpo.get("error") or {}).get("message", "") if isinstance(corpo, dict) else ""
        raise ErrorePagamento(f"Stripe: {messaggio or 'errore ' + str(r.status_code)}")
    return corpo


def crea_sessione(fornitore, pagamento, ritorno, annulla):
    """(id del fornitore, url della pagina di pagamento)."""
    if fornitore.tipo == fornitore.FINTO:
        return f"finto_{pagamento.pk}", reverse("pagamenti:finto", args=[pagamento.pk])
    if fornitore.tipo == fornitore.PAYPAL:
        return _ordine_paypal(fornitore, pagamento, ritorno, annulla)
    fattura = pagamento.fattura
    dati = {
        "mode": "payment", "success_url": ritorno, "cancel_url": annulla, "client_reference_id": str(pagamento.pk),
        "metadata[pagamento]": str(pagamento.pk), "payment_intent_data[metadata][pagamento]": str(pagamento.pk),
        "line_items[0][quantity]": "1", "line_items[0][price_data][currency]": "eur",
        "line_items[0][price_data][unit_amount]": str(int(pagamento.importo * 100)),
        "line_items[0][price_data][product_data][name]": f"Fattura {fattura.numero} del {fattura.data:%d/%m/%Y}",
        "line_items[0][price_data][product_data][description]": str(fattura.azienda)[:200],
    }
    sessione = _stripe(fornitore, "POST", "/checkout/sessions", dati, idempotenza=f"adabox-pagamento-{pagamento.pk}")
    return sessione["id"], sessione["url"]


def esito(fornitore, pagamento):
    """(pagato, riferimento del pagamento) chiedendo al fornitore: non ci si fida del ritorno nel browser."""
    if fornitore.tipo == fornitore.FINTO:
        return pagamento.stato == pagamento.PAGATO, pagamento.riferimento
    if fornitore.tipo == fornitore.PAYPAL:
        return _esito_paypal(fornitore, pagamento)
    sessione = _stripe(fornitore, "GET", f"/checkout/sessions/{pagamento.id_esterno}")
    return sessione.get("payment_status") == "paid", sessione.get("payment_intent") or sessione["id"]


def prova(fornitore):
    """Controlla la chiave (il saldo del conto): ErrorePagamento se non va."""
    if fornitore.tipo == fornitore.STRIPE:
        _stripe(fornitore, "GET", "/balance")
    elif fornitore.tipo == fornitore.PAYPAL:
        _token_paypal(fornitore)


def evento_stripe(fornitore, corpo, firma):
    """L'evento di un webhook Stripe, se la firma è giusta e recente; ErrorePagamento altrimenti."""
    segreto = fornitore.segreto_webhook()
    if not segreto:
        raise ErrorePagamento("Manca il segreto dei webhook.")
    parti = {}
    for pezzo in (firma or "").split(","):
        chiave, _, valore = pezzo.partition("=")
        parti.setdefault(chiave.strip(), []).append(valore.strip())
    try:
        istante = int(parti.get("t", ["0"])[0])
    except ValueError:
        istante = 0
    if abs(time.time() - istante) > TOLLERANZA_WEBHOOK:
        raise ErrorePagamento("Firma del webhook scaduta.")
    atteso = hmac.new(segreto.encode(), f"{istante}.".encode() + corpo, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(atteso, v) for v in parti.get("v1", [])):
        raise ErrorePagamento("Firma del webhook non valida.")
    return json.loads(corpo)


# ---------- PayPal (Orders v2): il cliente approva su PayPal, al ritorno (o dal webhook) si cattura il pagamento

def _base_paypal(fornitore):
    return PAYPAL_SANDBOX if fornitore.sandbox else PAYPAL


def _risposta(r, chi):
    try:
        corpo = r.json() if r.content else {}
    except ValueError as e:
        raise ErrorePagamento(f"{chi} ha risposto in modo illeggibile (HTTP {r.status_code})") from e
    if r.status_code >= 400:
        messaggio = ""
        if isinstance(corpo, dict):
            dettagli = corpo.get("details") or [{}]
            messaggio = (dettagli[0] or {}).get("description") or corpo.get("message") or corpo.get("error_description") or ""
        raise ErrorePagamento(f"{chi}: {messaggio or 'errore ' + str(r.status_code)}")
    return corpo


def _token_paypal(fornitore):
    if not fornitore.client_id or not fornitore.chiave():
        raise ErrorePagamento("Per PayPal servono il Client ID e il segreto dell'app.")
    client = _client()
    try:
        r = client.post(f"{_base_paypal(fornitore)}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                        auth=(fornitore.client_id, fornitore.chiave()))
    except httpx.HTTPError as e:
        raise ErrorePagamento(f"PayPal non risponde: {type(e).__name__}") from e
    finally:
        if HTTP is None:
            client.close()
    return _risposta(r, "PayPal")["access_token"]


def _paypal(fornitore, metodo, percorso, json_=None, idempotenza=""):
    intestazioni = {"Authorization": f"Bearer {_token_paypal(fornitore)}", "Content-Type": "application/json",
                    "Prefer": "return=representation"}
    if idempotenza:
        intestazioni["PayPal-Request-Id"] = idempotenza
    client = _client()
    try:
        r = client.request(metodo, f"{_base_paypal(fornitore)}{percorso}", json=json_, headers=intestazioni)
    except httpx.HTTPError as e:
        raise ErrorePagamento(f"PayPal non risponde: {type(e).__name__}") from e
    finally:
        if HTTP is None:
            client.close()
    return _risposta(r, "PayPal")


def _ordine_paypal(fornitore, pagamento, ritorno, annulla):
    fattura = pagamento.fattura
    dati = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": str(pagamento.pk), "custom_id": str(pagamento.pk), "invoice_id": f"adabox-{pagamento.pk}",
            "description": f"Fattura {fattura.numero} del {fattura.data:%d/%m/%Y}"[:127],
            "amount": {"currency_code": "EUR", "value": f"{pagamento.importo:.2f}"},
        }],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": str(fattura.azienda)[:127], "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING",
            "locale": "it-IT", "return_url": ritorno, "cancel_url": annulla}}},
    }
    ordine = _paypal(fornitore, "POST", "/v2/checkout/orders", dati, idempotenza=f"adabox-pagamento-{pagamento.pk}")
    link = next((l["href"] for l in ordine.get("links", []) if l.get("rel") in ("payer-action", "approve")), "")
    if not link:
        raise ErrorePagamento("PayPal non ha dato la pagina di pagamento.")
    return ordine["id"], link


def _cattura(ordine):
    """L'id della cattura completata dell'ordine, o ""."""
    for unita in ordine.get("purchase_units") or []:
        for c in ((unita.get("payments") or {}).get("captures") or []):
            if c.get("status") == "COMPLETED":
                return c.get("id", "")
    return ""


def _esito_paypal(fornitore, pagamento):
    """Un ordine approvato dal cliente si cattura qui (una volta sola: la cattura è idempotente per PayPal)."""
    ordine = _paypal(fornitore, "GET", f"/v2/checkout/orders/{pagamento.id_esterno}")
    if ordine.get("status") == "APPROVED":
        ordine = _paypal(fornitore, "POST", f"/v2/checkout/orders/{pagamento.id_esterno}/capture", {},
                         idempotenza=f"adabox-cattura-{pagamento.pk}")
    cattura = _cattura(ordine)
    return bool(ordine.get("status") == "COMPLETED" and cattura), cattura or ordine.get("id", "")


def evento_paypal(fornitore, corpo, intestazioni):
    """L'evento di un webhook PayPal, se PayPal stesso conferma la firma; ErrorePagamento altrimenti."""
    webhook_id = fornitore.segreto_webhook()
    if not webhook_id:
        raise ErrorePagamento("Manca l'ID del webhook.")
    try:
        evento = json.loads(corpo)
    except ValueError as e:
        raise ErrorePagamento("Evento illeggibile.") from e
    verifica = _paypal(fornitore, "POST", "/v1/notifications/verify-webhook-signature", {
        "auth_algo": intestazioni.get("Paypal-Auth-Algo", ""), "cert_url": intestazioni.get("Paypal-Cert-Url", ""),
        "transmission_id": intestazioni.get("Paypal-Transmission-Id", ""),
        "transmission_sig": intestazioni.get("Paypal-Transmission-Sig", ""),
        "transmission_time": intestazioni.get("Paypal-Transmission-Time", ""),
        "webhook_id": webhook_id, "webhook_event": evento})
    if verifica.get("verification_status") != "SUCCESS":
        raise ErrorePagamento("Firma del webhook non valida.")
    return evento


def ordine_dell_evento(evento):
    """L'id dell'ordine PayPal a cui si riferisce un evento (ordine approvato o pagamento catturato), o ""."""
    risorsa = evento.get("resource") or {}
    if evento.get("event_type", "").startswith("CHECKOUT.ORDER."):
        return risorsa.get("id", "")
    return ((risorsa.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id", "")
