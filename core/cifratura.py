"""Segreti nel database (chiavi API, password): cifrati con Fernet, mai salvati in chiaro.

La chiave è CHIAVE_CIFRATURA (una chiave Fernet) o, se manca, una derivata da SECRET_KEY: cambiarla rende
illeggibili i segreti già salvati."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class SegretoIlleggibile(ValueError):
    pass


def _fernet():
    chiave = settings.CHIAVE_CIFRATURA
    if not chiave:
        chiave = base64.urlsafe_b64encode(hashlib.sha256(f"cifratura:{settings.SECRET_KEY}".encode()).digest())
    return Fernet(chiave)


def cifra(testo):
    return _fernet().encrypt(testo.encode()).decode() if testo else ""


def decifra(cifrato):
    if not cifrato:
        return ""
    try:
        return _fernet().decrypt(cifrato.encode()).decode()
    except InvalidToken as e:
        raise SegretoIlleggibile("segreto non decifrabile (è cambiata la chiave di cifratura?)") from e


def mascherato(testo):
    """Per mostrarlo: solo gli ultimi 4 caratteri."""
    return f"••••{testo[-4:]}" if testo else ""
