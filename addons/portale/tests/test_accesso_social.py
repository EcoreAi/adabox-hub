"""COM-10: accesso al portale con Google e Microsoft, provato contro un servizio OpenID Connect simulato (chiave RSA
generata qui, discovery, JWKS, endpoint del token). Entra solo chi è già invitato; Microsoft conferma dall'email."""
import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx2 as httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.urls import reverse

from contatti.models import Contatto
from core import cifratura
from core.models import Azienda
from portale import oidc
from portale.inviti import invita
from portale.models import IdentitaEsterna, ProviderAccesso

CHIAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ESTRANEA = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwt(claims, chiave=CHIAVE, kid="k1", alg="RS256"):
    testa = _b64(json.dumps({"alg": alg, "kid": kid}).encode())
    corpo = _b64(json.dumps(claims).encode())
    firma = chiave.sign(f"{testa}.{corpo}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{testa}.{corpo}.{_b64(firma)}"


class Servizio:
    """Il servizio simulato: risponde a discovery, JWKS e token come Google o Microsoft."""

    def __init__(self, tipo):
        self.tipo, self.claims, self.chiave, self.richieste = tipo, {}, CHIAVE, []
        self.issuer = "https://accounts.google.com" if tipo == "google" else "https://login.microsoftonline.com/{tenantid}/v2.0"

    def __call__(self, request):
        self.richieste.append(request)
        url = str(request.url)
        if url.endswith("openid-configuration"):
            return httpx.Response(200, json={"issuer": self.issuer, "authorization_endpoint": "https://idp.test/auth",
                                             "token_endpoint": "https://idp.test/token", "jwks_uri": "https://idp.test/jwks"})
        if url.endswith("/jwks"):
            n = CHIAVE.public_key().public_numbers()
            return httpx.Response(200, json={"keys": [{"kty": "RSA", "kid": "k1", "n": _b64(n.n.to_bytes(256, "big")), "e": _b64(n.e.to_bytes(3, "big"))}]})
        if url.endswith("/token"):
            return httpx.Response(200, json={"id_token": _jwt(self.claims, self.chiave)})
        return httpx.Response(404)


@pytest.fixture
def scena(db, settings, monkeypatch):
    cache.clear()
    settings.SITO_URL = "https://hub.test"
    az = Azienda.objects.get(pk=1)
    rossi = Contatto.objects.create(azienda=az, nome="Rossi Srl", cliente=True)
    anna = Contatto.objects.create(azienda=az, nome="Anna Rossi", tipo="persona", societa=rossi, email="anna@rossi.it")
    accesso = invita(anna, User.objects.create_superuser("sara", "sara@example.com", "x"))
    mail.outbox.clear()
    servizi = {}

    def http():
        return httpx.Client(transport=httpx.MockTransport(lambda r: servizi[r.url.host if "idp" not in r.url.host else "corrente"](r)))
    monkeypatch.setattr(oidc, "_http", http)

    def provider(tipo):
        p = ProviderAccesso.objects.create(tipo=tipo, client_id=f"app-{tipo}", segreto_cifrato=cifratura.cifra("s3greto"))
        s = Servizio(tipo)
        servizi.update({"accounts.google.com" if tipo == "google" else "login.microsoftonline.com": s, "corrente": s})
        return p, s
    return {"accesso": accesso, "utente": accesso.utente, "provider": provider}


def _giro(client, tipo, servizio, **claims):
    """Login page → servizio → ritorno, con le affermazioni che il servizio mette nell'id_token."""
    r = client.get(reverse("portale:accedi", args=[tipo]))
    assert r.status_code == 302 and r.url.startswith("https://idp.test/auth?")
    q = {k: v[0] for k, v in parse_qs(urlparse(r.url).query).items()}
    assert q["code_challenge_method"] == "S256" and q["redirect_uri"] == f"https://hub.test/portale/accedi/{tipo}/ritorno/"
    servizio.claims = {"iss": servizio.issuer.replace("{tenantid}", "t1"), "aud": f"app-{tipo}", "sub": "sogg-1", "tid": "t1",
                       "exp": time.time() + 600, "iat": time.time(), "nonce": q["nonce"], **claims}
    return client.get(reverse("portale:accedi_ritorno", args=[tipo]), {"state": q["state"], "code": "c0d1ce"})


def test_bottoni_nella_pagina_di_accesso(client, scena):
    assert "Accedi con Google" not in client.get(reverse("login")).content.decode()
    scena["provider"]("google")
    assert "Accedi con Google" in client.get(reverse("login")).content.decode()


def test_google_con_email_verificata_entra_e_si_collega(client, scena):
    p, s = scena["provider"]("google")
    r = _giro(client, "google", s, email="Anna@Rossi.it", email_verified=True)
    assert r.status_code == 302 and r.url == reverse("portale:home")
    assert int(client.session["_auth_user_id"]) == scena["utente"].pk
    token = parse_qs(s.richieste[-2].content.decode())                 # lo scambio del codice porta PKCE e segreto
    assert token["code_verifier"] and token["client_secret"] == ["s3greto"]
    assert IdentitaEsterna.objects.get().utente == scena["utente"]
    client.logout()
    r = _giro(client, "google", s, email="altra@gmail.com", email_verified=True)   # poi la riconosce dal soggetto
    assert r.url == reverse("portale:home")


def test_microsoft_conferma_dall_email(client, scena):
    p, s = scena["provider"]("microsoft")
    r = _giro(client, "microsoft", s, email="anna@rossi.it")
    assert r.status_code == 200 and "Controlla la posta" in r.content.decode() and "_auth_user_id" not in client.session
    (email,) = mail.outbox
    link = next(riga for riga in email.body.splitlines() if "/portale/accedi/conferma/" in riga).replace("https://hub.test", "")
    assert client.get(link).status_code == 200 and not IdentitaEsterna.objects.exists()   # il GET non collega
    client.post(link)
    assert IdentitaEsterna.objects.get().tipo == "microsoft"
    r = _giro(client, "microsoft", s, email="anna@rossi.it")
    assert r.url == reverse("portale:home")


def test_non_invitati_e_token_falsi(client, scena):
    p, s = scena["provider"]("google")
    r = _giro(client, "google", s, email="estraneo@gmail.com", email_verified=True)
    assert r.url == reverse("login") and not IdentitaEsterna.objects.exists()           # niente registrazioni
    s.chiave = ESTRANEA                                                                   # firma di un altro
    assert _giro(client, "google", s, email="anna@rossi.it", email_verified=True).url == reverse("login")
    s.chiave = CHIAVE
    assert _giro(client, "google", s, email="anna@rossi.it", email_verified=True, aud="altra-app").url == reverse("login")
    assert _giro(client, "google", s, email="anna@rossi.it", email_verified=True, exp=time.time() - 3600).url == reverse("login")
    assert _giro(client, "google", s, email="anna@rossi.it", email_verified=True, nonce="rubato").url == reverse("login")
    assert "_auth_user_id" not in client.session
    r = client.get(reverse("portale:accedi_ritorno", args=["google"]), {"state": "x", "code": "y"})   # senza sessione
    assert r.url == reverse("login")
    scena["utente"].is_active = False                                                     # accesso sospeso
    scena["utente"].save()
    assert _giro(client, "google", s, email="anna@rossi.it", email_verified=True).url == reverse("login")


def test_interni_non_entrano_cosi(client, scena):
    User.objects.create_user("marco", "marco@azienda.it", "x")
    p, s = scena["provider"]("google")
    assert _giro(client, "google", s, email="marco@azienda.it", email_verified=True).url == reverse("login")


def test_verifica_in_due_passaggi_anche_qui(client, scena):
    from core import due_fattori as df2
    df = df2.prepara(scena["utente"])
    df2.attiva(scena["utente"]) if callable(getattr(df2, "attiva", None)) else None
    df = df2.di(scena["utente"])
    if df is None or df.attiva_dal is None:
        from django.utils import timezone
        df.attiva_dal = timezone.now()
        df.save()
    p, s = scena["provider"]("google")
    r = _giro(client, "google", s, email="anna@rossi.it", email_verified=True)
    assert r.url == reverse("due_fattori_accesso") and "_auth_user_id" not in client.session
