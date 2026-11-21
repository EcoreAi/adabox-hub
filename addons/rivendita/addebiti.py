"""Gli addebiti mensili: per ogni istanza e mese, che cosa c'è da fatturare. Il portale non emette fatture da solo:
prepara l'importo, tiene lo stato (da fatturare, fatturato, pagato) e, se sull'istanza del portale c'è il modulo
Fatturazione, crea la fattura in bozza.

Il canone del mese è la media dei canoni di ogni giorno: il lavoro pianificato registra ogni giorno il canone di quel
giorno (piano, prezzo per utente, suite, moduli in più), così un cambio di piano a metà mese, un'istanza nata o spenta
durante il mese pesano per i giorni in cui hanno contato, senza tenere un registro dei cambi. I giorni saltati (worker
fermo) si recuperano con il canone del giorno in cui si riparte.
Il mese si chiude dal giorno 2 del mese dopo, quando l'ultimo consumo dell'assistente è arrivato: all'importo del canone
si aggiunge l'assistente a consumo o misto di quel mese (ConsumoAI.importo)."""
import calendar
import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Addebito, ConsumoAI, Istanza

CENTESIMO = Decimal("0.01")


def _giorni_del_mese(mese):
    return calendar.monthrange(mese.year, mese.month)[1]


@transaction.atomic
def registra_giorno(istanza, oggi):
    """Aggiunge all'addebito del mese i giorni non ancora contati, fino a oggi, con il canone di oggi."""
    mese = oggi.replace(day=1)
    addebito, _ = Addebito.objects.select_for_update().get_or_create(istanza=istanza, mese=mese, defaults={"piano": istanza.piano.nome})
    if addebito.stato != Addebito.APERTO or (addebito.ultimo_giorno and addebito.ultimo_giorno >= oggi):
        return addebito
    giorni = (oggi - addebito.ultimo_giorno).days if addebito.ultimo_giorno else 1     # il primo giorno visto conta da solo
    addebito.giorni += giorni
    addebito.somma_canoni += istanza.canone_mese() * giorni
    addebito.ultimo_giorno, addebito.piano = oggi, istanza.piano.nome
    addebito.canone = (addebito.somma_canoni / _giorni_del_mese(mese)).quantize(CENTESIMO)
    addebito.totale = addebito.canone
    addebito.save()
    return addebito


@transaction.atomic
def chiudi(addebito):
    """Ferma l'addebito: canone dei giorni contati più l'assistente a consumo del mese. Senza importo non c'è niente da fatturare."""
    addebito = Addebito.objects.select_for_update().get(pk=addebito.pk)
    if addebito.stato != Addebito.APERTO:
        return addebito
    giorni_mese = _giorni_del_mese(addebito.mese)
    consumo = ConsumoAI.objects.filter(istanza=addebito.istanza, mese=addebito.mese).first()
    addebito.canone = (addebito.somma_canoni / giorni_mese).quantize(CENTESIMO)
    addebito.ai = consumo.importo if consumo else Decimal(0)
    addebito.totale = addebito.canone + addebito.ai
    righe = [f"Canone {addebito.piano}: {addebito.giorni} giorni su {giorni_mese}"]
    if consumo and consumo.importo:
        righe.append(f"Assistente AI ({consumo.get_formula_display()}): {consumo.costo_fornito:.2f} $ sul piano"
                     + (f", quota {consumo.quota:.2f} $" if consumo.quota else ""))
    addebito.dettaglio = "\n".join(righe)
    addebito.stato = Addebito.DA_FATTURARE if addebito.totale > 0 else Addebito.NIENTE
    addebito.chiuso_il = timezone.now()
    addebito.save()
    return addebito


def giro(oggi=None):
    """Voce `cron` del manifest, una volta al giorno: conta il giorno per le istanze attive e chiude i mesi finiti."""
    oggi = oggi or timezone.localdate()
    contate = 0
    for istanza in Istanza.objects.filter(attiva=True).select_related("piano").prefetch_related("suite", "moduli_extra"):
        registra_giorno(istanza, oggi)
        contate += 1
    limite = oggi.replace(day=1) if oggi.day >= 2 else (oggi.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    chiusi = 0
    for addebito in Addebito.objects.filter(stato=Addebito.APERTO, mese__lt=limite):
        chiudi(addebito)
        chiusi += 1
    return f"istanze contate: {contate}" + (f", mesi chiusi: {chiusi}" if chiusi else "")


def crea_fattura(addebito, azienda, utente=None):
    """La fattura in bozza per l'addebito, con il modulo Fatturazione del portale: una riga per il canone e una per
    l'assistente. Il cliente è il contatto collegato all'istanza o quello con lo stesso nome. ValueError con il motivo
    se non si può."""
    from django.apps import apps
    if not apps.is_installed("fatturazione"):
        raise ValueError("Su questa istanza non c'è il modulo Fatturazione.")
    if addebito.stato != Addebito.DA_FATTURARE:
        raise ValueError("L'addebito non è da fatturare.")
    if azienda is None:
        raise ValueError("Scegli l'azienda che emette la fattura.")
    Contatto, Fattura, RigaFattura = (apps.get_model(*n.split(".")) for n in ("contatti.Contatto", "fatturazione.Fattura", "fatturazione.RigaFattura"))
    istanza = addebito.istanza
    clienti = Contatto.objects.filter(azienda=azienda)                    # i contatti sono dell'azienda che fattura
    clienti = clienti.filter(pk=istanza.contatto) if istanza.contatto else clienti.filter(nome__iexact=istanza.cliente)
    if clienti.count() != 1:
        raise ValueError(f"Non trovo un solo contatto per «{istanza.cliente}»: indica il numero del contatto nella scheda dell'istanza.")
    aliquota = apps.get_model("fiscale.AliquotaIva").objects.filter(attiva=True, percentuale=22).order_by("pk").first()
    if aliquota is None:                                 # senza aliquota la fattura non avrebbe imponibile
        raise ValueError("Non trovo l'aliquota IVA al 22% tra quelle attive: creala nei dati fiscali.")
    periodo = f"{addebito.mese:%m/%Y}"
    with transaction.atomic():
        fattura = Fattura.objects.create(azienda=azienda, cliente=clienti.first(), causale=f"adabox {periodo}"[:200])
        for descrizione, importo in ((f"Canone adabox {addebito.piano} · {periodo}", addebito.canone), (f"Assistente AI · {periodo}", addebito.ai)):
            if importo:
                RigaFattura.objects.create(fattura=fattura, descrizione=descrizione[:250], quantita=1, prezzo=importo, aliquota=aliquota)
        fattura.ricalcola()
        addebito.fattura, addebito.stato = fattura.pk, Addebito.FATTURATO
        addebito.save(update_fields=["fattura", "stato"])
    return fattura
