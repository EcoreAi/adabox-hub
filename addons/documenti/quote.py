"""Quote dello spazio (MB): dell'azienda, di ogni utente per i suoi spazi personali, di ogni spazio condiviso.
Contano i file dei documenti (non gli allegati dei record, che restano dei record), le versioni e il cestino."""
from django.conf import settings
from django.db.models import Sum

from .models import Documento, QuotaUtente, Spazio, Versione

MB = 1024 * 1024


class QuotaSuperata(ValueError):
    pass


def parametro(chiave, azienda, default):
    from core import parametri
    try:
        valore = parametri.leggi(f"documenti.{chiave}", azienda)
    except KeyError:
        return default
    return default if valore in (None, "") else valore


def _uso(documenti):
    file = documenti.filter(allegato__isnull=True).aggregate(t=Sum("dimensione"))["t"] or 0
    versioni = Versione.objects.filter(documento__in=documenti).aggregate(t=Sum("dimensione"))["t"] or 0
    return file + versioni


def uso_azienda(azienda):
    return _uso(Documento.objects.filter(azienda=azienda))


def uso_spazi(spazi):
    return _uso(Documento.objects.filter(cartella__spazio__in=spazi))


def uso_personale(utente, azienda):
    return uso_spazi(Spazio.objects.filter(azienda=azienda, tipo=Spazio.PERSONALE, proprietario=utente))


def quota_azienda(azienda):
    return int(parametro("quota_azienda_mb", azienda, 0)) * MB


def quota_utente(utente, azienda):
    propria = QuotaUtente.objects.filter(azienda=azienda, utente=utente).values_list("quota_mb", flat=True).first()
    return int(propria if propria is not None else parametro("quota_utente_mb", azienda, 0)) * MB


def max_file_mb(azienda):
    """La dimensione massima di un file per l'azienda, entro il tetto del server."""
    return min(int(parametro("file_max_mb", azienda, 20)), settings.DOCUMENTI_FILE_MAX_MB)


def riepilogo(spazio):
    """{usato, quota} in byte per la barra d'uso di uno spazio (quota 0 = senza limite proprio)."""
    if spazio.personale:
        return {"usato": uso_personale(spazio.proprietario, spazio.azienda),
                "quota": quota_utente(spazio.proprietario, spazio.azienda), "di": "dei tuoi spazi personali"}
    return {"usato": uso_spazi([spazio]), "quota": spazio.quota_mb * MB, "di": "dello spazio"}


def _mb(byte):
    return f"{byte / MB:,.0f}".replace(",", ".")


def controlla(cartella, aggiunta):
    """Solleva QuotaSuperata se `aggiunta` byte in `cartella` superano una delle quote che la riguardano."""
    azienda = cartella.azienda
    limite = quota_azienda(azienda)
    if limite and uso_azienda(azienda) + aggiunta > limite:
        raise QuotaSuperata(f"spazio dell'azienda esaurito ({_mb(limite)} MB): chiedi all'amministratore")
    spazio = cartella.spazio
    if spazio is None:
        return
    if spazio.personale:
        limite = quota_utente(spazio.proprietario, azienda)
        if limite and uso_personale(spazio.proprietario, azienda) + aggiunta > limite:
            raise QuotaSuperata(f"quota personale esaurita ({_mb(limite)} MB): libera spazio o chiedi di più "
                                "all'amministratore")
    elif spazio.quota_mb and uso_spazi([spazio]) + aggiunta > spazio.quota_mb * MB:
        raise QuotaSuperata(f"quota dello spazio «{spazio}» esaurita ({spazio.quota_mb} MB)")
