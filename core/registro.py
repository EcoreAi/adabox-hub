"""Il registro delle modifiche: chi ha cambiato cosa, quando e da dove, su tutti i record che hanno una vista, anche quelli
senza chatter. Le righe di un documento finiscono sotto il documento.

Passa dai segnali di Django: `QuerySet.update()` e `bulk_create()` non li inviano, quindi non compaiono qui. Nemmeno i
campi molti-a-molti. I segreti non entrano mai, e i testi lunghi si tagliano."""
import contextvars
import logging
from contextlib import contextmanager
from functools import wraps

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save, pre_save

from .viste import registry
from .viste.interroga import SENSIBILE

log = logging.getLogger("core.registro")
_autore = contextvars.ContextVar("registro_autore", default=(None, "sistema"))
LUNGHEZZA_VALORE = 300
_mappa = None


def imposta(utente, origine):
    return _autore.set((utente, origine))


@contextmanager
def origine(nome, utente=None):
    """Tutto ciò che succede qui dentro risulta fatto da `nome`; l'utente resta quello di prima se non se ne dà uno."""
    attuale = _autore.get()
    token = _autore.set((utente if utente is not None else attuale[0], nome))
    try:
        yield
    finally:
        _autore.reset(token)


class Middleware:
    """Per le pagine: l'utente è già noto. L'API lo imposta dopo, quando ha verificato il token."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        utente = getattr(request, "user", None)
        token = _autore.set((utente if getattr(utente, "is_authenticated", False) else None, "api" if request.path.startswith("/api/") else "ui"))
        try:
            return self.get_response(request)
        finally:
            _autore.reset(token)


def _registrati():
    """{modello: nome del campo verso il documento, o None}: i modelli con una vista e le righe dei loro documenti."""
    global _mappa
    if _mappa is None:
        from django.conf import settings
        registry.autodiscover(["core", *settings.ADDONS_ATTIVI])
        mappa = {}
        for modulo in ["core", *settings.ADDONS_ATTIVI]:
            for vista in registry.viste_di(modulo):
                if vista.storico:
                    mappa[vista.model] = None
                    for riga in vista.inlines:
                        mappa.setdefault(riga.model, riga.fk)
        _mappa = mappa
    return _mappa


def azzera():
    """Solo per i test."""
    global _mappa
    _mappa = None


def _campi(modello):
    for f in modello._meta.concrete_fields:
        if f.primary_key or SENSIBILE.search(f.name) or getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False):
            continue
        if isinstance(f, models.BinaryField):
            continue
        yield f


def _testo(obj):
    """Il nome di un record: un __str__ che fallisce non deve far perdere il salvataggio."""
    try:
        return str(obj)
    except Exception:  # noqa: BLE001 - qualunque errore in un __str__ altrui
        return f"{type(obj).__name__} {obj.pk}"


def _valore(v):
    if v is None or v == "":
        return ""
    return str(v)[:LUNGHEZZA_VALORE]


def _leggibile(f, v):
    if v in (None, ""):
        return ""
    if f.is_relation:
        collegato = f.related_model._default_manager.filter(pk=v).first()
        return _valore(_testo(collegato) if collegato is not None else v)
    if f.choices:
        return _valore(dict(f.flatchoices).get(v, v))
    if isinstance(v, bool):
        return "sì" if v else "no"
    return _valore(v)


def _mai_bloccante(funzione):
    """Il registro racconta i salvataggi, non li decide: un suo errore finisce nel log, mai a chi sta salvando."""
    @wraps(funzione)
    def involucro(sender, instance, **kwargs):
        try:
            with transaction.atomic():                 # un errore del database non deve rovinare la transazione di chi salva
                return funzione(sender, instance, **kwargs)
        except Exception:  # noqa: BLE001
            log.exception("registro delle modifiche: %s su %s %s", funzione.__name__, sender.__name__, instance.pk)
    return involucro


@_mai_bloccante
def prima(sender, instance, raw=False, **_):
    """Prima di salvare si leggono i valori di adesso: dopo non ci sarebbero più."""
    if raw or sender not in _registrati() or instance.pk is None or instance._state.adding:
        return
    instance._registro_prima = sender._default_manager.filter(pk=instance.pk).values(*[f.attname for f in _campi(sender)]).first()


def _differenze(sender, instance, update_fields):
    vecchi = getattr(instance, "_registro_prima", None)
    if not vecchi:
        return []
    modifiche = []
    for f in _campi(sender):
        if update_fields is not None and f.name not in update_fields and f.attname not in update_fields:
            continue
        adesso = getattr(instance, f.attname)
        if vecchi[f.attname] != adesso and _valore(vecchi[f.attname]) != _valore(adesso):
            modifiche.append({"campo": str(f.verbose_name), "prima": _leggibile(f, vecchi[f.attname]), "dopo": _leggibile(f, adesso)})
    return modifiche


def _scrivi(sender, instance, azione, modifiche):
    from .models import RegistroModifica
    fk = _registrati()[sender]
    try:
        documento = getattr(instance, fk, None) if fk else instance
    except ObjectDoesNotExist:                         # il documento se ne sta andando con le sue righe
        return
    if documento is None:
        return
    utente, origine_ = _autore.get()
    testo = _testo(documento)
    if fk:
        riga = _testo(instance)[:80]
        modifiche = [{**m, "riga": riga} for m in modifiche] or [{"riga": riga, "campo": "", "prima": "", "dopo": ""}]
    RegistroModifica.objects.create(
        azienda_id=getattr(documento, "azienda_id", None), content_type=ContentType.objects.get_for_model(type(documento)), object_id=documento.pk,
        oggetto=testo[:200], azione=RegistroModifica.AGGIORNATO if fk else azione, utente=utente,
        utente_nome=(utente.get_username() if utente else "")[:150], origine=origine_, modifiche=modifiche)


@_mai_bloccante
def dopo(sender, instance, created=False, raw=False, update_fields=None, **_):
    if raw or sender not in _registrati():
        return
    from .models import RegistroModifica
    if created:
        _scrivi(sender, instance, RegistroModifica.CREATO, [])
        return
    modifiche = _differenze(sender, instance, update_fields)
    if modifiche:
        _scrivi(sender, instance, RegistroModifica.AGGIORNATO, modifiche)


@_mai_bloccante
def eliminato(sender, instance, **_):
    if sender not in _registrati():
        return
    from .models import RegistroModifica
    _scrivi(sender, instance, RegistroModifica.ELIMINATO, [])


def collega():
    pre_save.connect(prima, dispatch_uid="core.registro.prima")
    post_save.connect(dopo, dispatch_uid="core.registro.dopo")
    post_delete.connect(eliminato, dispatch_uid="core.registro.eliminato")


def di(request, obj, quante=20):
    """Le ultime modifiche di un record, per chi può vedere il registro."""
    from .models import RegistroModifica
    if not request.user.has_perm("core.view_registromodifica") or type(obj) not in _registrati():
        return []
    return list(RegistroModifica.objects.filter(content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk)[:quante])
