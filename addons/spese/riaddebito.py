"""Riaddebito al cliente: le spese approvate con un cliente diventano righe di una fattura in bozza (se c'è
Fatturazione). Il rimborso al dipendente si può abbinare al movimento bancario che lo paga (se c'è Banca)."""
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import NotaSpese, RigaSpesa


def disponibile():
    return apps.is_installed("fatturazione")


def da_riaddebitare(azienda):
    """Le spese con un cliente, di note approvate o rimborsate, non ancora in una fattura valida."""
    return (RigaSpesa.objects.filter(nota__azienda=azienda, nota__stato__in=(NotaSpese.APPROVATA, NotaSpese.RIMBORSATA),
                                     cliente__isnull=False, riaddebitata_in__isnull=True, importo__gt=0)
            .select_related("cliente", "categoria", "nota__dipendente").order_by("cliente__nome", "data", "pk"))


def per_cliente(azienda):
    """[{cliente, righe, totale}] per la pagina «Da riaddebitare»."""
    gruppi = {}
    for r in da_riaddebitare(azienda):
        g = gruppi.setdefault(r.cliente_id, {"cliente": r.cliente, "righe": [], "totale": 0})
        g["righe"].append(r)
        g["totale"] += r.importo
    return sorted(gruppi.values(), key=lambda g: -g["totale"])


@transaction.atomic
def fattura(azienda, cliente, pk_righe):
    """Fattura in bozza al cliente con le spese scelte, una riga per spesa (importo come prezzo, l'IVA predefinita
    della riga; si correggono nella bozza). Le spese restano legate alla fattura finché vale."""
    if not disponibile():
        raise ValidationError("Serve il modulo Fatturazione.")
    Fattura, RigaFattura = apps.get_model("fatturazione", "Fattura"), apps.get_model("fatturazione", "RigaFattura")
    righe = list(da_riaddebitare(azienda).select_for_update(of=("self",)).filter(cliente=cliente, pk__in=pk_righe))
    if not righe:
        raise ValidationError("Scegli almeno una spesa ancora da riaddebitare.")
    f = Fattura.objects.create(azienda=azienda, cliente=cliente, causale="Riaddebito spese")
    for r in righe:
        RigaFattura.objects.create(fattura=f, descrizione=f"Spesa del {r.data:%d/%m/%Y}: {r.descrizione} ({r.categoria})"[:250],
                                   prezzo=r.importo, quantita=1)
    RigaSpesa.objects.filter(pk__in=[r.pk for r in righe]).update(riaddebitata_in=f.pk)
    f.ricalcola()
    return f


def libera(fattura_pk):
    RigaSpesa.objects.filter(riaddebitata_in=fattura_pk).update(riaddebitata_in=None)


def fattura_cambiata(sender, instance, **kwargs):
    """Fattura annullata, o stornata per intero da una nota di credito emessa: le spese tornano da riaddebitare."""
    if instance.stato == instance.ANNULLATA:
        libera(instance.pk)
    elif instance.stato == instance.EMESSA and instance.tipo == instance.NOTA_CREDITO and instance.fattura_origine_id \
            and instance.fattura_origine.stornata:
        libera(instance.fattura_origine_id)


def fattura_eliminata(sender, instance, **kwargs):
    libera(instance.pk)


# ---------- rimborso abbinato alla banca

def banca_disponibile():
    return apps.is_installed("banca")


def movimenti_per(nota):
    if not banca_disponibile():
        return []
    from banca import abbina
    return abbina.candidati_uscita(nota.azienda, nota.totale)


def pagamento_di(nota):
    """Il movimento bancario abbinato al rimborso, o None."""
    if not banca_disponibile():
        return None
    from banca import abbina
    a = abbina.abbinamenti_di(nota).first()
    return a.movimento if a else None
