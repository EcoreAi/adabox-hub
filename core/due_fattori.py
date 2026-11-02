"""Autenticazione a due fattori: codici TOTP (Google Authenticator, Microsoft Authenticator, 1Password…), codici di
recupero, dispositivi fidati per 30 giorni e obbligo scelto dall'amministratore."""
import hashlib
import hmac
import secrets
import time

import pyotp
import segno
from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db.models import F
from django.utils import timezone

from . import cifratura
from .models import DueFattori, Parametro

CHIAVE_OBBLIGO = "core.due_fattori_obbligo"
NESSUNO, AMMINISTRATORI, TUTTI = "nessuno", "amministratori", "tutti"
OBBLIGHI = [(NESSUNO, "Facoltativa: ognuno decide per sé"), (AMMINISTRATORI, "Obbligatoria per gli amministratori"),
            (TUTTI, "Obbligatoria per tutti gli utenti interni")]
COOKIE_FIDATO = "adabox_dispositivo"
SALE_FIDATO = "core.due_fattori.fidato"
GIORNI_FIDATO = 30
QUANTI_CODICI = 10
ALFABETO_CODICI = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PASSO = 30


def leggi_obbligo():
    p = Parametro.objects.filter(chiave=CHIAVE_OBBLIGO, azienda__isnull=True).first()
    return p.valore if p is not None and p.valore in dict(OBBLIGHI) else NESSUNO


def scrivi_obbligo(valore):
    Parametro.objects.update_or_create(chiave=CHIAVE_OBBLIGO, azienda=None, defaults={"valore": valore})


def obbligatoria_per(utente):
    obbligo = leggi_obbligo()
    return obbligo == TUTTI or (obbligo == AMMINISTRATORI and (utente.is_superuser or utente.is_staff))


def di(utente):
    return DueFattori.objects.filter(utente=utente).first()


def attiva(utente):
    return DueFattori.objects.filter(utente=utente, attiva_dal__isnull=False).exists()


def prepara(utente):
    """Il segreto della procedura di attivazione: resta lo stesso finché non si conclude."""
    df, _ = DueFattori.objects.get_or_create(
        utente=utente, defaults={"segreto_cifrato": cifratura.cifra(pyotp.random_base32())})
    return df


def segreto(df):
    return cifratura.decifra(df.segreto_cifrato)


def uri(df):
    return pyotp.TOTP(segreto(df)).provisioning_uri(name=df.utente.get_username(), issuer_name=settings.THEME.get("brand", ""))


def qr_svg(df):
    return segno.make(uri(df), error="m").svg_inline(scale=5, border=2, dark="#0f172a", light="#ffffff")


def segreto_a_gruppi(df):
    testo = segreto(df)
    return " ".join(testo[i:i + 4] for i in range(0, len(testo), 4))


def _impronta(codice):
    return hashlib.sha256(f"{settings.SECRET_KEY}:{codice}".encode()).hexdigest()


def _normalizza(codice):
    return "".join((codice or "").split()).replace("-", "").upper()


def nuovi_codici(df):
    """Genera i codici di recupero e li restituisce in chiaro (si mostrano una volta sola)."""
    codici = ["".join(secrets.choice(ALFABETO_CODICI) for _ in range(8)) for _ in range(QUANTI_CODICI)]
    df.codici_recupero = [_impronta(c) for c in codici]
    df.save(update_fields=["codici_recupero"])
    return [f"{c[:4]}-{c[4:]}" for c in codici]


def bloccata(df):
    return bool(df.bloccata_fino and df.bloccata_fino > timezone.now())


def _totp_valido(df, codice):
    """Finestra di ±30 secondi; ogni passo vale una volta sola, anche con due richieste insieme."""
    totp = pyotp.TOTP(segreto(df))
    adesso = int(time.time()) // PASSO
    for passo in (adesso - 1, adesso, adesso + 1):
        if passo > df.ultimo_passo and hmac.compare_digest(totp.at(passo * PASSO), codice):
            return DueFattori.objects.filter(pk=df.pk, ultimo_passo__lt=passo).update(ultimo_passo=passo) == 1
    return False


def verifica(df, codice, recupero_ammesso=True):
    """"totp" o "recupero" se il codice è buono (e azzera i fallimenti), None altrimenti (e li conta: dopo troppi
    errori la verifica resta bloccata, come il blocco dell'accesso con la password)."""
    if bloccata(df):
        return None
    codice = _normalizza(codice)
    esito = None
    if codice.isdigit() and len(codice) == 6:
        esito = "totp" if _totp_valido(df, codice) else None
    elif recupero_ammesso and len(codice) == 8:
        impronta = _impronta(codice)
        if impronta in df.codici_recupero:
            df.codici_recupero.remove(impronta)
            df.save(update_fields=["codici_recupero"])
            esito = "recupero"
    if esito:
        DueFattori.objects.filter(pk=df.pk).update(fallimenti=0, bloccata_fino=None)
        return esito
    DueFattori.objects.filter(pk=df.pk).update(fallimenti=F("fallimenti") + 1)
    df.refresh_from_db()
    if df.fallimenti >= settings.AXES_FAILURE_LIMIT:
        DueFattori.objects.filter(pk=df.pk).update(fallimenti=0, bloccata_fino=timezone.now() + settings.AXES_COOLOFF_TIME)
        df.refresh_from_db()
    return None


def _valore_fidato(df):
    """Legato a utente, password e generazione: cambiando la password o revocando, i dispositivi non valgono più."""
    return {"u": df.utente_id, "g": df.generazione, "h": df.utente.get_session_auth_hash()}


def ricorda_dispositivo(risposta, df):
    risposta.set_cookie(COOKIE_FIDATO, signing.dumps(_valore_fidato(df), salt=SALE_FIDATO),
                        max_age=GIORNI_FIDATO * 86400, httponly=True, samesite="Lax",
                        secure=settings.SESSION_COOKIE_SECURE)


def dispositivo_fidato(request, df):
    try:
        valore = signing.loads(request.COOKIES.get(COOKIE_FIDATO, ""), salt=SALE_FIDATO, max_age=GIORNI_FIDATO * 86400)
    except signing.BadSignature:
        return False
    return valore == _valore_fidato(df)


def avvisa(utente, oggetto, testo):
    if utente.email:
        send_mail(oggetto, f"{testo}\n\nSe non sei stato tu, contatta subito l'amministratore.", None, [utente.email],
                  fail_silently=True)
