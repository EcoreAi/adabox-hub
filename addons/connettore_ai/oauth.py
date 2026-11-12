"""Il server di autorizzazione (OAuth 2.1): richiesta, codice, token, rinnovo, revoca.

- Solo il flusso con codice e PKCE S256; i client sono pubblici, o con un segreto se si sono registrati chiedendolo.
- Codici e token sono casuali e opachi: qui resta l'impronta. Un token vale solo su questa istanza perché solo qui se
  ne trova l'impronta; `resource`, quando arriva, deve essere l'indirizzo MCP di questa istanza.
- Il token di rinnovo dei client pubblici si ruota a ogni uso; riusato dopo la finestra di grazia, il collegamento si
  revoca: è il segno di un token copiato. Ai client con un segreto resta lo stesso (Google lo chiede espressamente).
- Nessun token di terzi si accetta né si inoltra."""
import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import clienti, stato
from .models import Codice, ChatCollegata, Token

DURATA_CODICE = timedelta(minutes=5)
DURATA_ACCESSO = timedelta(hours=1)
DURATA_RINNOVO = timedelta(days=90)                  # senza uso: a ogni rinnovo riparte
GRAZIA_RINNOVO = timedelta(seconds=60)               # la risposta al rinnovo può perdersi: lo stesso token si riaccetta
SFIDA_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")        # base64url di uno SHA-256
VERIFICATORE_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


class ErroreOAuth(Exception):
    """Errore da restituire al client: al token come JSON, all'autorizzazione come parametri del ritorno."""

    def __init__(self, codice, descrizione="", stato_http=400):
        super().__init__(descrizione or codice)
        self.codice, self.descrizione, self.stato_http = codice, descrizione, stato_http


def impronta(chiaro):
    return hashlib.sha256(chiaro.encode()).hexdigest()


# ---------- richiesta di autorizzazione ----------

@dataclass
class Richiesta:
    client: object
    redirect_uri: str
    sfida: str
    stato: str


def leggi_richiesta(p):
    """La richiesta di autorizzazione controllata. ClientNonValido se client o ritorno non valgono (non si rimanda
    indietro nessuno); ErroreOAuth, con `redirect_uri` e `stato`, per gli errori che tornano al client."""
    client = clienti.trova(p.get("client_id"))
    uri = p.get("redirect_uri") or (client.redirect_uris[0] if len(client.redirect_uris) == 1 else "")
    if not uri or not clienti.ritorno_del_client(client, uri) or not clienti.fornitore_di(uri):
        raise clienti.ClientNonValido("indirizzo di ritorno non dichiarato dal client o non ammesso", "invalid_request")
    richiesta = Richiesta(client, uri, p.get("code_challenge", ""), p.get("state", ""))

    def errore(codice, descrizione):
        e = ErroreOAuth(codice, descrizione)
        e.richiesta = richiesta
        return e
    if p.get("response_type") != "code":
        raise errore("unsupported_response_type", "si offre solo response_type=code")
    if p.get("code_challenge_method") != "S256" or not SFIDA_RE.match(richiesta.sfida):
        raise errore("invalid_request", "serve PKCE con code_challenge_method=S256")
    if p.get("resource") and not stato.stessa_risorsa(p["resource"]):
        raise errore("invalid_target", "resource non è l'indirizzo MCP di questa istanza")
    return richiesta


def emetti_codice(richiesta, utente, azienda, app):
    chiaro = "cai_k_" + secrets.token_urlsafe(32)
    Codice.objects.create(impronta=impronta(chiaro), client=richiesta.client, utente=utente, azienda=azienda,
                          redirect_uri=richiesta.redirect_uri, sfida=richiesta.sfida, app=list(app),
                          scade=timezone.now() + DURATA_CODICE)
    return chiaro


# ---------- token ----------

def _client_autenticato(p, basic):
    """Il client della richiesta al token, con il segreto se ne ha uno (nel corpo o nell'intestazione Basic)."""
    client_id, segreto = (basic or (p.get("client_id", ""), p.get("client_secret", "")))
    try:
        client = clienti.trova(client_id, rileggi=False)
    except clienti.ClientNonValido as e:
        raise ErroreOAuth("invalid_client", e.descrizione, 401) from e
    if client.impronta and not secrets.compare_digest(impronta(segreto or ""), client.impronta):
        raise ErroreOAuth("invalid_client", "segreto del client mancante o non valido", 401)
    return client


def _coppia(collegamento, rinnovo=""):
    """Un token di accesso nuovo e uno di rinnovo (nuovo, o `rinnovo` se resta lo stesso), nella forma della risposta
    del token endpoint."""
    adesso = timezone.now()
    accesso = "cai_a_" + secrets.token_urlsafe(32)
    nuovi = [Token(collegamento=collegamento, tipo=Token.ACCESSO, impronta=impronta(accesso), scade=adesso + DURATA_ACCESSO)]
    if not rinnovo:
        rinnovo = "cai_r_" + secrets.token_urlsafe(32)
        nuovi.append(Token(collegamento=collegamento, tipo=Token.RINNOVO, impronta=impronta(rinnovo), scade=adesso + DURATA_RINNOVO))
    Token.objects.bulk_create(nuovi)
    return {"access_token": accesso, "token_type": "Bearer", "expires_in": int(DURATA_ACCESSO.total_seconds()),
            "refresh_token": rinnovo, "scope": stato.AMBITO}


def _pkce(verificatore, sfida):
    if not VERIFICATORE_RE.match(verificatore or ""):
        return False
    calcolata = base64.urlsafe_b64encode(hashlib.sha256(verificatore.encode()).digest()).rstrip(b"=").decode()
    return secrets.compare_digest(calcolata, sfida)


def _scambia_codice(p, client):
    """Il codice vale una volta. Riusato, si revoca il collegamento che aveva fatto nascere: chi lo ha usato per primo
    potrebbe non essere il client. La revoca sta fuori dalla transazione, così resta anche se la richiesta fallisce."""
    riusato = None
    with transaction.atomic():
        codice = Codice.objects.select_for_update().filter(impronta=impronta(p.get("code", ""))).first()
        if codice is None or codice.client_id != client.pk:
            raise ErroreOAuth("invalid_grant", "codice sconosciuto")
        if codice.usato is not None:
            riusato = codice
        else:
            if codice.scade < timezone.now():
                raise ErroreOAuth("invalid_grant", "codice scaduto")
            if p.get("redirect_uri") and p["redirect_uri"] != codice.redirect_uri:
                raise ErroreOAuth("invalid_grant", "redirect_uri diverso da quello dell'autorizzazione")
            if not _pkce(p.get("code_verifier"), codice.sfida):
                raise ErroreOAuth("invalid_grant", "code_verifier non valido")
            if p.get("resource") and not stato.stessa_risorsa(p["resource"]):
                raise ErroreOAuth("invalid_target", "resource non è l'indirizzo MCP di questa istanza")
            if not any(a.pk == codice.azienda_id for a in stato.aziende_collegabili(codice.utente)):
                raise ErroreOAuth("invalid_grant", "la persona non può più collegare questa azienda")
            collegamento = ChatCollegata.objects.create(
                utente=codice.utente, azienda=codice.azienda, client=client, app=codice.app,
                fornitore=clienti.fornitore_di(codice.redirect_uri) or client.fornitore)
            codice.usato, codice.collegamento = timezone.now(), collegamento
            codice.save(update_fields=["usato", "collegamento"])
            type(client).objects.filter(pk=client.pk).update(ultimo_uso=timezone.now())
            return _coppia(collegamento)
    if riusato.collegamento is not None:
        riusato.collegamento.revoca()
    raise ErroreOAuth("invalid_grant", "codice già usato")


def _rinnova(p, client):
    """Fuori dalla transazione la revoca per riuso: deve restare anche se la richiesta finisce in errore."""
    da_revocare = None
    with transaction.atomic():
        token = (Token.objects.select_for_update().select_related("collegamento")
                 .filter(impronta=impronta(p.get("refresh_token", "")), tipo=Token.RINNOVO).first())
        adesso = timezone.now()
        if token is None or token.collegamento.client_id != client.pk or token.scade < adesso:
            raise ErroreOAuth("invalid_grant", "token di rinnovo sconosciuto o scaduto")
        collegamento = token.collegamento
        if token.usato is not None and adesso - token.usato > GRAZIA_RINNOVO:
            da_revocare = collegamento
        elif not stato.ancora_valido(collegamento):
            raise ErroreOAuth("invalid_grant", "collegamento revocato o non più ammesso")
        elif client.impronta:                   # client con un segreto: lo stesso token, che dura altri 90 giorni
            token.scade = adesso + DURATA_RINNOVO
            token.save(update_fields=["scade"])
            return _coppia(collegamento, rinnovo=p["refresh_token"])
        else:
            if token.usato is None:
                token.usato = adesso
                token.save(update_fields=["usato"])
            return _coppia(collegamento)
    da_revocare.revoca()
    raise ErroreOAuth("invalid_grant", "token di rinnovo già usato: il collegamento è stato revocato")


def emetti(p, basic=None):
    """La risposta del token endpoint per i parametri del corpo. `basic`: (client_id, segreto) dall'intestazione."""
    client = _client_autenticato(p, basic)
    tipo = p.get("grant_type")
    if tipo == "authorization_code":
        return _scambia_codice(p, client)
    if tipo == "refresh_token":
        return _rinnova(p, client)
    raise ErroreOAuth("unsupported_grant_type", "si offrono authorization_code e refresh_token")


def collegamento_di(chiaro):
    """Il collegamento di un token di accesso valido, None altrimenti. Si ricontrolla tutto a ogni chiamata."""
    if not chiaro:
        return None
    token = (Token.objects.select_related("collegamento__utente", "collegamento__azienda", "collegamento__client")
             .filter(impronta=impronta(chiaro), tipo=Token.ACCESSO, scade__gt=timezone.now()).first())
    if token is None or not stato.ancora_valido(token.collegamento):
        return None
    return token.collegamento


def revoca_token(p, basic=None):
    """RFC 7009: il token indicato (di accesso o di rinnovo) revoca tutto il suo collegamento. Mai un errore se il
    token non esiste."""
    client = _client_autenticato(p, basic)
    token = Token.objects.select_related("collegamento").filter(impronta=impronta(p.get("token", ""))).first()
    if token is not None and token.collegamento.client_id == client.pk:
        token.collegamento.revoca()
