"""Lettura automatica dei conti (PSD2) tramite un aggregatore: GoCardless Bank Account Data, via API REST senza librerie,
e uno simulato per prove e demo. Il titolare dà il consenso sul sito della sua banca; poi un lavoro pianificato legge i
movimenti nuovi e li passa dalla stessa deduplica degli estratti caricati a mano (abbina.salva)."""
import datetime
import logging
from decimal import Decimal, InvalidOperation

import httpx2 as httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from . import abbina, estratti
from .models import Aggregatore, CollegamentoConto, normalizza_iban

log = logging.getLogger(__name__)
API = "https://bankaccountdata.gocardless.com/api/v2"
HTTP = None                                    # solo per i test: un client httpx finto
SOVRAPPOSIZIONE = 5                            # giorni riletti a ogni giro: i movimenti contabilizzati in ritardo non si perdono
AVVISO_GIORNI = 10                             # avvisa quando il consenso scade entro tanti giorni


class ErroreBanca(RuntimeError):
    pass


def aggregatore_attivo(azienda):
    return Aggregatore.objects.filter(azienda=azienda, attivo=True).order_by("pk").first() if azienda else None


# ---------- GoCardless

def _client():
    return HTTP or httpx.Client(timeout=30, trust_env=False)


def _chiama(metodo, percorso, token=None, json_=None, params=None):
    intestazioni = {"Accept": "application/json"}
    if token:
        intestazioni["Authorization"] = f"Bearer {token}"
    client = _client()
    try:
        r = client.request(metodo, f"{API}{percorso}", json=json_, params=params, headers=intestazioni)
    except httpx.HTTPError as e:
        raise ErroreBanca(f"Il servizio non risponde: {type(e).__name__}") from e
    finally:
        if HTTP is None:
            client.close()
    try:
        corpo = r.json() if r.content else {}
    except ValueError as e:
        raise ErroreBanca(f"Risposta illeggibile (HTTP {r.status_code})") from e
    if r.status_code >= 400:
        dettaglio = corpo.get("detail") or corpo.get("summary") if isinstance(corpo, dict) else ""
        if r.status_code == 429:
            dettaglio = "troppe letture per oggi: la banca ne consente poche al giorno, si riprova più tardi"
        raise ErroreBanca(f"{dettaglio or 'errore'} (HTTP {r.status_code})")
    return corpo


def _token(aggregatore):
    if not aggregatore.secret_id or not aggregatore.secret_key():
        raise ErroreBanca("Mancano Secret ID e Secret Key del servizio.")
    return _chiama("POST", "/token/new/", json_={"secret_id": aggregatore.secret_id, "secret_key": aggregatore.secret_key()})["access"]


FINTE_BANCHE = [{"id": "FINTA_BANCA_IT", "name": "Banca Simulata", "bic": "FINTITMM", "transaction_total_days": "540"}]


def banche(aggregatore, paese="IT"):
    """[{id, name, bic, transaction_total_days}] delle banche del paese."""
    if aggregatore.tipo == Aggregatore.FINTO:
        return FINTE_BANCHE
    return _chiama("GET", "/institutions/", _token(aggregatore), params={"country": paese})


def avvia(conto, aggregatore, istituto, nome_istituto="", giorni_storico=90, utente=None):
    """Crea (o rinnova) il collegamento e la richiesta di consenso: restituisce il CollegamentoConto con link_consenso."""
    collegamento, _ = CollegamentoConto.objects.update_or_create(conto=conto, defaults={
        "azienda": conto.azienda, "aggregatore": aggregatore, "istituto": istituto, "nome_istituto": nome_istituto[:200],
        "stato": CollegamentoConto.IN_ATTESA, "giorni_storico": giorni_storico, "utente": utente, "errore": "",
        "richiesta": "", "conto_esterno": "", "link_consenso": ""})
    ritorno = f"{settings.SITO_URL}{reverse('banca:collega_ritorno', args=[collegamento.pk])}"
    if aggregatore.tipo == Aggregatore.FINTO:
        collegamento.richiesta = f"finta-{collegamento.pk}"
        collegamento.link_consenso = f"{ritorno}?ref=finta-{collegamento.pk}"
    else:
        token = _token(aggregatore)
        accordo = _chiama("POST", "/agreements/enduser/", token, json_={
            "institution_id": istituto, "max_historical_days": giorni_storico, "access_valid_for_days": 90,
            "access_scope": ["balances", "details", "transactions"]})
        richiesta = _chiama("POST", "/requisitions/", token, json_={
            "redirect": ritorno, "institution_id": istituto, "agreement": accordo["id"], "user_language": "IT",
            "reference": f"adabox-{collegamento.pk}-{int(timezone.now().timestamp())}"})
        collegamento.richiesta, collegamento.link_consenso = richiesta["id"], richiesta["link"]
        collegamento.scade_il = timezone.localdate() + datetime.timedelta(days=int(accordo.get("access_valid_for_days") or 90))
    collegamento.save()
    return collegamento


def completa(collegamento):
    """Dopo il consenso: trova fra i conti autorizzati quello con l'IBAN del nostro conto e lo attiva."""
    aggregatore = collegamento.aggregatore
    if aggregatore.tipo == Aggregatore.FINTO:
        collegamento.conto_esterno = f"finto-{collegamento.conto_id}"
    else:
        token = _token(aggregatore)
        richiesta = _chiama("GET", f"/requisitions/{collegamento.richiesta}/", token)
        if richiesta.get("status") != "LN" or not richiesta.get("accounts"):
            raise ErroreBanca("La banca non ha dato il consenso (o non ci sono conti autorizzati).")
        nostro = normalizza_iban(collegamento.conto.iban)
        trovato = ""
        for conto_esterno in richiesta["accounts"]:
            dettagli = _chiama("GET", f"/accounts/{conto_esterno}/details/", token).get("account") or {}
            if normalizza_iban(dettagli.get("iban")) == nostro:
                trovato = conto_esterno
                break
        if not trovato:
            raise ErroreBanca(f"Fra i conti autorizzati non c'è {collegamento.conto.iban}: rifai il consenso scegliendo quel conto.")
        collegamento.conto_esterno = trovato
    collegamento.stato, collegamento.errore = CollegamentoConto.ATTIVO, ""
    if collegamento.scade_il is None:
        collegamento.scade_il = timezone.localdate() + datetime.timedelta(days=90)
    collegamento.save()
    return collegamento


def _importo(valore):
    try:
        return Decimal(str(valore)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return None


def _data(valore):
    try:
        return datetime.date.fromisoformat(str(valore)[:10])
    except (TypeError, ValueError):
        return None


def riga(t):
    """Una transazione PSD2 (formato Berlin Group) come riga di estratto, o None se illeggibile."""
    importo, data = _importo((t.get("transactionAmount") or {}).get("amount")), _data(t.get("bookingDate") or t.get("valueDate"))
    if importo is None or data is None:
        return None
    entra = importo > 0
    descrizione = t.get("remittanceInformationUnstructured") or " ".join(t.get("remittanceInformationUnstructuredArray") or []) \
        or t.get("remittanceInformationStructured") or t.get("additionalInformation") or ""
    controparte = (t.get("debtorName") if entra else t.get("creditorName")) or ""
    iban = ((t.get("debtorAccount") if entra else t.get("creditorAccount")) or {}).get("iban", "")
    return estratti.Riga(data=data, importo=importo, descrizione=" ".join(str(descrizione).split()), valuta=_data(t.get("valueDate")),
                         controparte=controparte, iban_controparte=normalizza_iban(iban),
                         riferimento=str(t.get("transactionId") or t.get("internalTransactionId") or t.get("entryReference") or ""))


def _movimenti_finti(collegamento, dal):
    oggi = timezone.localdate()
    return [{"transactionId": f"finto-{collegamento.pk}-{oggi:%Y%m%d}-1", "bookingDate": oggi.isoformat(),
             "transactionAmount": {"amount": "122.00", "currency": "EUR"}, "debtorName": "Cliente Simulato",
             "remittanceInformationUnstructured": "Bonifico simulato dalla Banca Simulata"}], (Decimal("1000.00"), oggi)


def _leggi_dal_servizio(collegamento, dal):
    """([transazioni contabilizzate], (saldo, data) o None)."""
    if collegamento.aggregatore.tipo == Aggregatore.FINTO:
        return _movimenti_finti(collegamento, dal)
    token = _token(collegamento.aggregatore)
    corpo = _chiama("GET", f"/accounts/{collegamento.conto_esterno}/transactions/", token, params={"date_from": dal.isoformat()})
    transazioni = (corpo.get("transactions") or {}).get("booked") or []
    saldo = None
    try:
        saldi = _chiama("GET", f"/accounts/{collegamento.conto_esterno}/balances/", token).get("balances") or []
        scelto = next((b for tipo in ("closingBooked", "interimBooked", "expected", "interimAvailable") for b in saldi
                       if b.get("balanceType") == tipo), None)
        if scelto:
            saldo = (_importo((scelto.get("balanceAmount") or {}).get("amount")), _data(scelto.get("referenceDate")) or timezone.localdate())
    except ErroreBanca:
        pass                                     # il saldo è un di più: i movimenti contano
    return transazioni, saldo


def leggi(collegamento, utente=None):
    """Legge i movimenti nuovi del conto e li salva senza doppioni. Restituisce l'Importazione (o None se non è attivo)."""
    if collegamento.stato != CollegamentoConto.ATTIVO:
        return None
    oggi = timezone.localdate()
    if collegamento.scade_il and collegamento.scade_il < oggi:
        collegamento.stato = CollegamentoConto.SCADUTO
        collegamento.save(update_fields=["stato"])
        return None
    if collegamento.letto_fino_al:
        dal = collegamento.letto_fino_al - datetime.timedelta(days=SOVRAPPOSIZIONE)
    else:
        dal = oggi - datetime.timedelta(days=collegamento.giorni_storico)
    try:
        transazioni, saldo = _leggi_dal_servizio(collegamento, dal)
    except ErroreBanca as e:
        testo = str(e)
        collegamento.errore = testo[:300]
        if "401" in testo or "EUA" in testo or "expired" in testo.lower():
            collegamento.stato = CollegamentoConto.SCADUTO
        collegamento.ultima_lettura = timezone.now()
        collegamento.save(update_fields=["errore", "stato", "ultima_lettura"])
        raise
    righe = [r for r in (riga(t) for t in transazioni) if r is not None]
    righe.sort(key=lambda r: (r.data, r.riferimento))
    estratto = estratti.Estratto(formato="psd2", righe=righe, scartate=len(transazioni) - len(righe),
                                 saldo=saldo[0] if saldo else None, saldo_al=saldo[1] if saldo else None)
    with transaction.atomic():
        esito = abbina.salva(collegamento.conto, estratto, f"Lettura automatica da {collegamento.nome_istituto or 'banca'}", utente)
        collegamento.ultima_lettura, collegamento.letto_fino_al, collegamento.errore = timezone.now(), oggi, ""
        collegamento.save(update_fields=["ultima_lettura", "letto_fino_al", "errore"])
        if not esito.nuovi and not esito.scartati:
            esito.delete()                       # una lettura senza novità non lascia una riga in Importazioni
    return esito


def giro():
    """Il lavoro pianificato: legge tutti i conti collegati e attivi. Un conto che sbaglia non ferma gli altri."""
    letti = 0
    for c in CollegamentoConto.objects.filter(stato=CollegamentoConto.ATTIVO, aggregatore__attivo=True).select_related("conto", "aggregatore"):
        try:
            if leggi(c) is not None:
                letti += 1
        except ErroreBanca as e:
            log.warning("banca: lettura di %s non riuscita: %s", c, e)
    return letti


def in_scadenza(azienda):
    """I collegamenti il cui consenso scade presto o è già scaduto: da rinnovare."""
    limite = timezone.localdate() + datetime.timedelta(days=AVVISO_GIORNI)
    return CollegamentoConto.objects.filter(azienda=azienda).filter(
        Q(stato=CollegamentoConto.SCADUTO) | Q(stato=CollegamentoConto.ATTIVO, scade_il__lte=limite)).select_related("conto")
