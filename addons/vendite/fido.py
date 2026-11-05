"""Il fido del cliente: quanto ci deve già, tra scadenze aperte e ordini confermati non ancora fatturati.

Senza un fido sul contatto non si controlla nulla. Oltre il fido la conferma avvisa, oppure si ferma se sul contatto
è scelto il blocco. Le fatture sono facoltative: senza quel modulo contano solo gli ordini."""
from decimal import Decimal

from django.apps import apps

from core.viste.schede import euro

from .models import OrdineVendita


def _gia_fatturato(ordine):
    """Una fattura emessa ha già le sue scadenze: l'ordine non si conta due volte. Una bozza non ne ha ancora."""
    from fatturazione.models import Fattura
    from fatturazione.operazioni import fatture_attive
    return any(f.stato == Fattura.EMESSA for f in fatture_attive(ordine))


def esposizione(contatto):
    """{"scadenze", "ordini", "totale"}: gli importi aperti verso il cliente, IVA compresa."""
    ordini = list(OrdineVendita.objects.filter(cliente=contatto, stato=OrdineVendita.CONFERMATO))
    scadenze = Decimal(0)
    if apps.is_installed("fatturazione"):
        from fatturazione.models import Fattura, Scadenza
        aperte = Scadenza.objects.filter(fattura__cliente=contatto, fattura__stato=Fattura.EMESSA, pagata=False)
        scadenze = sum((s.residuo for s in aperte), Decimal(0))
        ordini = [o for o in ordini if not _gia_fatturato(o)]
    da_fatturare = sum((o.totale for o in ordini), Decimal(0))
    return {"scadenze": scadenze, "ordini": da_fatturare, "totale": scadenze + da_fatturare}


def situazione(contatto):
    """Il fido e quanto ne resta; None se il contatto non ha un fido."""
    if contatto.fido is None:
        return None
    dati = esposizione(contatto)
    return {**dati, "fido": contatto.fido, "disponibile": contatto.fido - dati["totale"],
            "superato": dati["totale"] > contatto.fido, "blocca": contatto.fido_blocca}


def controllo(ordine):
    """Cosa succederebbe confermando questo preventivo: None se resta nel fido, altrimenti i numeri e il testo."""
    dati = situazione(ordine.cliente)
    if dati is None or ordine.stato == OrdineVendita.CONFERMATO:
        return None
    dopo = dati["totale"] + ordine.totale
    if dopo <= dati["fido"]:
        return None
    return {**dati, "dopo": dopo, "oltre": dopo - dati["fido"],
            "testo": f"Fido di {ordine.cliente.nome} superato di {euro(dopo - dati['fido'])}: già aperti {euro(dati['totale'])}, "
                     f"questo documento {euro(ordine.totale)}, fido {euro(dati['fido'])}."}
