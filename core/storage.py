import os

from django.conf import settings
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
