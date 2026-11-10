import os

from django.conf import settings
from django.contrib.staticfiles.storage import ManifestStaticFilesStorage, StaticFilesStorage
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class StoragePrivato(FileSystemStorage):
    """File in PRIVATE_MEDIA_ROOT, senza URL pubblico: si leggono solo dalle viste con i permessi.
    La cartella si legge a ogni accesso (non al caricamento del modello), così segue i settings."""

    @property
    def base_location(self):
        return str(settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError("i file privati non hanno un URL pubblico: usare la vista di download")


class StaticConImpronta(ManifestStaticFilesStorage):
    """File statici con l'impronta del contenuto nel nome (admin.3f2a9c.css): un file cambiato ha un URL nuovo, e il
    browser non usa mai una copia vecchia in cache, nemmeno dei file di Django (l'admin dopo un aggiornamento).

    L'impronta si usa solo per i file che collectstatic ha messo nel manifest e solo con STATIC_IMPRONTA (di default
    senza DEBUG). Un file mancante dal manifest, o in sviluppo con runserver (che serve i sorgenti, senza impronta),
    ha l'URL di sempre invece di un errore. collectstatic copia anche i file col nome originale: chi li chiama per nome
    (es. da un JavaScript) continua a trovarli."""

    manifest_strict = False
    # i riferimenti alle source map (/*# sourceMappingURL=... */) restano come sono: le librerie vendorizzate citano
    # file .map che non distribuiamo, e collectstatic si fermerebbe. Servono solo agli strumenti per sviluppatori.
    patterns = tuple((estensione, tuple(p for p in schemi if "sourceMappingURL" not in (p if isinstance(p, str) else p[0])))
                     for estensione, schemi in ManifestStaticFilesStorage.patterns)

    def url(self, name, force=False):
        if getattr(settings, "STATIC_IMPRONTA", False) and name and self.hashed_files.get(self.hash_key(self.clean_name(name))):
            return super().url(name, force=True)
        return StaticFilesStorage.url(self, name)
