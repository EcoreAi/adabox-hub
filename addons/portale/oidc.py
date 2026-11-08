"""OpenID Connect per Google e Microsoft, senza librerie in più: codice di autorizzazione con PKCE, state e nonce in
sessione, id_token verificato con la chiave pubblica del servizio (RS256), emittente, destinatario e scadenza."""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import httpx2 as httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.core.cache import cache

from .models import ProviderAccesso

SCOPERTA = {
    ProviderAccesso.GOOGLE: "https://accounts.google.com/.well-known/openid-configuration",
    ProviderAccesso.MICROSOFT: "https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration",
}
TOLLERANZA = 120          # secondi di differenza ammessa tra gli orologi


class ErroreOidc(Exception):
    pass


def _http():
    """Il client HTTP (nei test si sostituisce con un servizio simulato)."""
    return httpx.Client(timeout=10, follow_redirects=False, trust_env=False)


def _json(url, dati=None):
    with _http() as client:
        r = client.post(url, data=dati, headers={"Accept": "application/json"}) if dati is not None else client.get(url)
    if r.status_code != 200:
        raise ErroreOidc(f"il servizio ha risposto {r.status_code}")
    return r.json()


def configurazione(provider):
    url = SCOPERTA[provider.tipo].format(tenant=provider.tenant or "common")
    chiave = "portale.oidc:" + hashlib.sha256(url.encode()).hexdigest()[:24]
    conf = cache.get(chiave)
    if conf is None:
        conf = _json(url)
        cache.set(chiave, conf, 3600)
    return conf


def _b64(testo):
    return base64.urlsafe_b64encode(testo).rstrip(b"=").decode()


def _d64(testo):
    return base64.urlsafe_b64decode(testo + "=" * (-len(testo) % 4))


def inizia(provider, redirect_uri):
    """(url a cui mandare il browser, dati da tenere in sessione)."""
    conf = configurazione(provider)
    verificatore = secrets.token_urlsafe(48)
    stato, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    parametri = {"client_id": provider.client_id, "response_type": "code", "scope": "openid email profile",
                 "redirect_uri": redirect_uri, "state": stato, "nonce": nonce, "prompt": "select_account",
                 "code_challenge": _b64(hashlib.sha256(verificatore.encode()).digest()), "code_challenge_method": "S256"}
    return f"{conf['authorization_endpoint']}?{urlencode(parametri)}", {
        "tipo": provider.tipo, "stato": stato, "nonce": nonce, "verificatore": verificatore, "t": time.time()}


def _chiave(conf, kid):
    for k in _json(conf["jwks_uri"]).get("keys", []):
        if k.get("kid") == kid and k.get("kty") == "RSA":
            n, e = (int.from_bytes(_d64(k[x]), "big") for x in ("n", "e"))
            return rsa.RSAPublicNumbers(e, n).public_key()
    raise ErroreOidc("chiave del servizio non trovata")


def verifica_id_token(provider, conf, token, nonce):
    """Le affermazioni (claims) dell'id_token, se firma, emittente, destinatario, scadenza e nonce tornano."""
    try:
        testa_b, corpo_b, firma_b = token.split(".")
        testa, corpo = json.loads(_d64(testa_b)), json.loads(_d64(corpo_b))
    except (ValueError, TypeError) as e:
        raise ErroreOidc("risposta del servizio non leggibile") from e
    if testa.get("alg") != "RS256":
        raise ErroreOidc("algoritmo di firma non ammesso")
    try:
        _chiave(conf, testa.get("kid")).verify(_d64(firma_b), f"{testa_b}.{corpo_b}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as e:
        raise ErroreOidc("firma non valida") from e
    emittente = conf["issuer"].replace("{tenantid}", str(corpo.get("tid", "")))
    adesso = time.time()
    if corpo.get("iss") != emittente:
        raise ErroreOidc("emittente non valido")
    destinatari = corpo.get("aud") if isinstance(corpo.get("aud"), list) else [corpo.get("aud")]
    if provider.client_id not in destinatari:
        raise ErroreOidc("token non destinato a questa applicazione")
    if float(corpo.get("exp", 0)) < adesso - TOLLERANZA or float(corpo.get("iat", adesso)) > adesso + TOLLERANZA:
        raise ErroreOidc("token scaduto")
    if not nonce or corpo.get("nonce") != nonce:
        raise ErroreOidc("nonce non valido")
    return corpo


def completa(provider, sessione, stato, codice, redirect_uri):
    """(soggetto, email, email verificata, nome) dopo il ritorno dal servizio."""
    if not sessione or sessione.get("tipo") != provider.tipo or not secrets.compare_digest(sessione.get("stato", ""), stato or ""):
        raise ErroreOidc("richiesta non riconosciuta: riprova ad accedere")
    if time.time() - sessione.get("t", 0) > 600:
        raise ErroreOidc("è passato troppo tempo: riprova ad accedere")
    conf = configurazione(provider)
    risposta = _json(conf["token_endpoint"], {
        "grant_type": "authorization_code", "code": codice, "redirect_uri": redirect_uri, "client_id": provider.client_id,
        "client_secret": provider.segreto, "code_verifier": sessione["verificatore"]})
    if not risposta.get("id_token"):
        raise ErroreOidc("il servizio non ha restituito l'identità")
    claims = verifica_id_token(provider, conf, risposta["id_token"], sessione["nonce"])
    email = (claims.get("email") or (claims.get("preferred_username") if "@" in str(claims.get("preferred_username", "")) else "") or "").lower()
    verificata = provider.tipo == ProviderAccesso.GOOGLE and claims.get("email_verified") is True
    return str(claims["sub"]), email, verificata, claims.get("name", "")
