"""I fornitori di pagamento: Stripe (Checkout, via API REST, senza librerie) e uno simulato per prove e demo.
Ogni fornitore sa creare la pagina di pagamento, dire se è stata pagata e verificare la firma dei suoi webhook."""
import hashlib
import hmac
import json
import time

import httpx2 as httpx
from django.urls import reverse

API = "https://api.stripe.com/v1"
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
    sessione = _stripe(fornitore, "GET", f"/checkout/sessions/{pagamento.id_esterno}")
    return sessione.get("payment_status") == "paid", sessione.get("payment_intent") or sessione["id"]


def prova(fornitore):
    """Controlla la chiave (il saldo del conto): ErrorePagamento se non va."""
    if fornitore.tipo == fornitore.STRIPE:
        _stripe(fornitore, "GET", "/balance")


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
