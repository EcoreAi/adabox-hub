"""Notifiche push (Web Push, RFC 8030/8291/8292) senza librerie in più: cifratura aes128gcm del messaggio per il
browser e firma VAPID ES256 con `cryptography`. Le chiavi VAPID si creano al primo uso nei file privati.
Si manda solo verso indirizzi https pubblici (core.rete.post_sicuro); un'iscrizione scaduta (404/410) si cancella."""
import base64
import json
import logging
import os
import struct
import time
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hmac import HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from django.conf import settings
from django.utils import timezone

log = logging.getLogger("core.push")


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _d64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _file_chiave():
    return Path(getattr(settings, "PRIVATE_MEDIA_ROOT", settings.BASE_DIR / "private")) / "vapid.pem"


def chiave_privata():
    percorso = _file_chiave()
    if percorso.exists():
        return serialization.load_pem_private_key(percorso.read_bytes(), password=None)
    chiave = ec.generate_private_key(ec.SECP256R1())
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_bytes(chiave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    os.chmod(percorso, 0o600)
    return chiave


def _pubblica_grezza(chiave):
    return chiave.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def chiave_pubblica():
    """La chiave pubblica VAPID (base64url) che il browser usa come applicationServerKey."""
    return _b64(_pubblica_grezza(chiave_privata()))


def _hkdf_extract(salt, ikm):
    h = HMAC(salt, hashes.SHA256())
    h.update(ikm)
    return h.finalize()


def _hkdf_expand(prk, info, lunghezza):
    return HKDFExpand(hashes.SHA256(), lunghezza, info).derive(prk)


def cifra(testo, p256dh, auth, salt=None, effimera=None):
    """Il corpo aes128gcm per il browser (RFC 8291)."""
    ua_pub = _d64(p256dh)
    segreto_auth = _d64(auth)
    effimera = effimera or ec.generate_private_key(ec.SECP256R1())
    as_pub = _pubblica_grezza(effimera)
    condiviso = effimera.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    ikm = _hkdf_expand(_hkdf_extract(segreto_auth, condiviso), b"WebPush: info\x00" + ua_pub + as_pub, 32)
    salt = salt or os.urandom(16)
    prk = _hkdf_extract(salt, ikm)
    cek = _hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    cifrato = AESGCM(cek).encrypt(nonce, testo + b"\x02", None)
    return salt + struct.pack("!I", 4096) + bytes([len(as_pub)]) + as_pub + cifrato


def vapid(endpoint):
    """L'intestazione Authorization VAPID per il servizio push dell'endpoint."""
    chiave = chiave_privata()
    parti = urlparse(endpoint)
    testa = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    corpo = _b64(json.dumps({"aud": f"{parti.scheme}://{parti.netloc}", "exp": int(time.time()) + 12 * 3600,
                             "sub": f"mailto:{settings.DEFAULT_FROM_EMAIL}" if "@" in str(getattr(settings, "DEFAULT_FROM_EMAIL", ""))
                             else settings.SITO_URL}).encode())
    r, s = decode_dss_signature(chiave.sign(f"{testa}.{corpo}".encode(), ec.ECDSA(hashes.SHA256())))
    firma = _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={testa}.{corpo}.{firma}, k={_b64(_pubblica_grezza(chiave))}"


def _invia_a(iscrizione, carico):
    from core import rete
    corpo = cifra(json.dumps(carico, ensure_ascii=False).encode(), iscrizione.p256dh, iscrizione.auth)
    intestazioni = {"TTL": "86400", "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                    "Urgency": "normal", "Authorization": vapid(iscrizione.endpoint)}
    return rete.post_sicuro(iscrizione.endpoint, corpo, intestazioni)


def invia(utente_id, titolo, testo="", url="/"):
    """Lavoro: la notifica a tutti i dispositivi dell'utente. Restituisce quanti l'hanno accettata."""
    from core.models import IscrizionePush
    carico = {"titolo": titolo[:120], "testo": (testo or "")[:240], "url": url or "/"}
    ok = 0
    for i in IscrizionePush.objects.filter(utente_id=utente_id):
        try:
            stato = _invia_a(i, carico)
        except Exception:                                    # noqa: BLE001 - rete o indirizzo rifiutato
            log.exception("push verso %s", i.endpoint[:60])
            continue
        if stato in (404, 410):                              # l'utente l'ha tolta dal browser
            i.delete()
        elif 200 <= stato < 300:
            ok += 1
            IscrizionePush.objects.filter(pk=i.pk).update(ultimo_invio=timezone.now())
    return ok


def accoda(utente, titolo, testo="", url="/"):
    from core import lavori
    from core.models import IscrizionePush
    if utente is None or not IscrizionePush.objects.filter(utente=utente).exists():
        return None
    return lavori.accoda("core.push.invia", utente_id=utente.pk, titolo=titolo, testo=testo, url=url)
