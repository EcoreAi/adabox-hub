"""PLT-16: app installabile (manifest, icone, service worker, pagina offline), pagina «In tasca» e notifiche Web Push
(RFC 8291 + VAPID) verificate decifrando come farebbe il browser."""
import base64
import json
import struct

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.contrib.auth.models import User

from core import push
from core.models import IscrizionePush


@pytest.fixture(autouse=True)
def chiavi(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _browser():
    privata = ec.generate_private_key(ec.SECP256R1())
    pubblica = privata.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return privata, _b64(pubblica), _b64(b"0123456789abcdef")


def _decifra(corpo, privata, p256dh, auth):
    """Come il browser (RFC 8291): legge l'intestazione, ricava chiave e nonce, decifra e toglie il delimitatore."""
    salt, rs, idlen = corpo[:16], struct.unpack("!I", corpo[16:20])[0], corpo[20]
    as_pub, cifrato = corpo[21:21 + idlen], corpo[21 + idlen:]
    assert rs == 4096 and idlen == 65
    ua_pub = push._d64(p256dh)
    condiviso = privata.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = push._hkdf_expand(push._hkdf_extract(push._d64(auth), condiviso), b"WebPush: info\x00" + ua_pub + as_pub, 32)
    prk = push._hkdf_extract(salt, ikm)
    chiaro = AESGCM(push._hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(
        push._hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12), cifrato, None)
    assert chiaro.endswith(b"\x02")
    return chiaro[:-1]


def test_cifratura_che_il_browser_sa_leggere():
    privata, p256dh, auth = _browser()
    corpo = push.cifra(b'{"titolo": "Ciao"}', p256dh, auth)
    assert json.loads(_decifra(corpo, privata, p256dh, auth)) == {"titolo": "Ciao"}


def test_firma_vapid(settings):
    settings.SITO_URL = "https://hub.test"
    intestazione = push.vapid("https://fcm.googleapis.com/fcm/send/abc")
    jwt, k = intestazione.removeprefix("vapid t=").split(", k=")
    testa, corpo, firma = jwt.split(".")
    claims = json.loads(push._d64(corpo))
    assert claims["aud"] == "https://fcm.googleapis.com" and claims["exp"] > 0
    grezza = push._d64(firma)
    pubblica = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push._d64(k))
    pubblica.verify(encode_dss_signature(int.from_bytes(grezza[:32], "big"), int.from_bytes(grezza[32:], "big")),
                    f"{testa}.{corpo}".encode(), ec.ECDSA(hashes.SHA256()))
    assert k == push.chiave_pubblica()                                    # la stessa chiave, conservata


@pytest.mark.django_db
def test_invio_e_iscrizioni_scadute(monkeypatch):
    u = User.objects.create_user("anna", "a@example.com", "x")
    privata, p256dh, auth = _browser()
    viva = IscrizionePush.objects.create(utente=u, endpoint="https://push.example.com/a", p256dh=p256dh, auth=auth)
    IscrizionePush.objects.create(utente=u, endpoint="https://push.example.com/b", p256dh=p256dh, auth=auth)
    mandati = []

    def finto(url, corpo, intestazioni, **kw):
        mandati.append((url, corpo, intestazioni))
        return 201 if url.endswith("/a") else 410
    monkeypatch.setattr("core.rete.post_sicuro", finto)
    assert push.invia(u.pk, "Nuova approvazione", "Preventivo 12", "/approvazioni/") == 1
    assert list(IscrizionePush.objects.values_list("pk", flat=True)) == [viva.pk]      # quella revocata se ne va
    url, corpo, intestazioni = mandati[0]
    assert intestazioni["Content-Encoding"] == "aes128gcm" and intestazioni["Authorization"].startswith("vapid t=")
    assert json.loads(_decifra(corpo, privata, p256dh, auth)) == {"titolo": "Nuova approvazione", "testo": "Preventivo 12", "url": "/approvazioni/"}


@pytest.mark.django_db
def test_dalle_notifiche_di_discuss(monkeypatch):
    from django.apps import apps
    if not apps.is_installed("discuss"):
        pytest.skip("Discuss non installato")
    from discuss import eventi
    u = User.objects.create_user("anna", "a@example.com", "x")
    privata, p256dh, auth = _browser()
    IscrizionePush.objects.create(utente=u, endpoint="https://push.example.com/a", p256dh=p256dh, auth=auth)
    mandati = []
    monkeypatch.setattr("core.rete.post_sicuro", lambda url, corpo, intestazioni, **kw: mandati.append(corpo) or 201)
    eventi.emetti("notifica", utente=u, tipo_notifica="menzione", titolo="Marco ti ha menzionato", testo="guarda qui", url="/x/")
    assert mandati and json.loads(_decifra(mandati[0], privata, p256dh, auth))["titolo"] == "Marco ti ha menzionato"


@pytest.mark.django_db
def test_iscrizione_dal_browser(client, superuser):
    privata, p256dh, auth = _browser()
    assert client.post("/push/iscrivi/", json.dumps({"endpoint": "http://interno/x", "keys": {"p256dh": p256dh, "auth": auth}}),
                       content_type="application/json").status_code == 400            # solo https
    r = client.post("/push/iscrivi/", json.dumps({"endpoint": "https://fcm.googleapis.com/fcm/send/xyz", "keys": {"p256dh": p256dh, "auth": auth}}),
                    content_type="application/json", HTTP_USER_AGENT="Telefono di prova")
    assert r.json()["attiva"] and IscrizionePush.objects.get().dispositivo == "Telefono di prova"
    client.post("/push/iscrivi/", json.dumps({"endpoint": "https://fcm.googleapis.com/fcm/send/xyz", "keys": {}, "disattiva": True}),
                content_type="application/json")
    assert not IscrizionePush.objects.exists()
    assert client.get("/push/chiave/").json()["chiave"] == push.chiave_pubblica()


@pytest.mark.django_db
def test_app_installabile_e_pagina_in_tasca(client, superuser):
    m = client.get("/manifest.webmanifest").json()
    assert m["display"] == "standalone" and m["start_url"].startswith("/tasca/") and any(i["sizes"] == "512x512" for i in m["icons"])
    sw = client.get("/sw.js")
    assert sw["Service-Worker-Allowed"] == "/" and "showNotification" in sw.content.decode()
    assert client.get("/icona-512.png").content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "Sei offline" in client.get("/offline/").content.decode()
    base = client.get("/dashboard/").content.decode()
    assert 'rel="manifest"' in base and "rete.js" in base
    tasca = client.get("/tasca/").content.decode()
    assert "Le mie attività" in tasca and "Da approvare" in tasca and "data-push" in tasca
    assert "Notifiche sul telefono" in client.get("/profilo/").content.decode()
