"""I file allegati ai messaggi della chat: privati come la chat, letti dall'assistente solo se serve (strumento
leggi_allegato), così un file grande non occupa la conversazione. Se ne va il messaggio, se ne va il file."""
from django.contrib.contenttypes.models import ContentType

from core import allegati as core_allegati
from core.allegati import AllegatoNonValido
from core.models import Allegato

from .models import MessaggioChat

ESTENSIONI = {"txt", "md", "csv", "tsv", "json", "xml", "html", "htm", "eml", "pdf", "docx", "xlsx", "xlsm"}
MASSIMO = 5


def controlla(file):
    """Prima di creare qualsiasi cosa: un file sbagliato non deve lasciare una chat a metà."""
    if len(file) > MASSIMO:
        raise AllegatoNonValido(f"Al massimo {MASSIMO} file per messaggio.")
    for f in file:
        nome = core_allegati.valida(f)
        if nome.rsplit(".", 1)[-1].lower() not in ESTENSIONI or "." not in nome:
            raise AllegatoNonValido(f"«{nome}»: l'assistente legge PDF, Word, Excel, CSV e file di testo. Le immagini non ancora.")


def di(messaggio):
    return list(Allegato.objects.filter(content_type=ContentType.objects.get_for_model(MessaggioChat), object_id=messaggio.pk))


def della_conversazione(conversazione):
    if conversazione is None:
        return Allegato.objects.none()
    return Allegato.objects.filter(content_type=ContentType.objects.get_for_model(MessaggioChat),
                                   object_id__in=MessaggioChat.objects.filter(conversazione=conversazione).values("pk"))


def nota(messaggio):
    """Per il modello, nel contesto del messaggio."""
    voci = di(messaggio)
    if not voci:
        return ""
    elenco = ", ".join(f"«{a.nome}» (allegato n. {a.pk})" for a in voci)
    return f"L'utente ha allegato a questo messaggio: {elenco}. Leggili con leggi_allegato prima di rispondere."


def togli_file(sender, instance, **_):
    for a in Allegato.objects.filter(content_type=ContentType.objects.get_for_model(MessaggioChat), object_id=instance.pk):
        a.file.delete(save=False)
        a.delete()
