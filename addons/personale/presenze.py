"""Timbrature e presenze: chi entra ed esce, quante ore ha lavorato ogni giorno rispetto a quelle previste, le assenze
approvate e le anomalie; il riepilogo del mese per il consulente del lavoro.

Il PIN del chiosco si conserva come impronta HMAC con la chiave segreta dell'istanza (non la password: deve essere
cercabile e unico per azienda); dopo troppi tentativi sbagliati il chiosco si ferma per qualche minuto."""
import datetime
import hashlib
import hmac
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import calendario_lavoro
from .models import Assenza, Dipendente, Timbratura

TENTATIVI = 5
BLOCCO_MINUTI = 5


def impronta_pin(pin):
    return hmac.new(settings.SECRET_KEY.encode(), f"pin:{pin}".encode(), hashlib.sha256).hexdigest()


def imposta_pin(dipendente, pin):
    """Il PIN (da 4 a 8 cifre), unico tra i dipendenti attivi dell'azienda."""
    pin = str(pin or "").strip()
    if not pin.isdigit() or not 4 <= len(pin) <= 8:
        raise ValueError("Il PIN è fatto di 4–8 cifre.")
    impronta = impronta_pin(pin)
    if Dipendente.objects.filter(azienda=dipendente.azienda, attivo=True, pin_impronta=impronta).exclude(pk=dipendente.pk).exists():
        raise ValueError("Questo PIN è già usato da un collega: scegline un altro.")
    dipendente.pin_impronta = impronta
    dipendente.save(update_fields=["pin_impronta"])


def bloccato(chiave):
    return cache.get(f"personale.chiosco:{chiave}", 0) >= TENTATIVI


def riconosci(azienda, codice, chiave_chiosco="chiosco"):
    """Il dipendente attivo con quel badge o quel PIN, oppure None (e un tentativo in meno)."""
    codice = str(codice or "").strip()
    if not codice or bloccato(chiave_chiosco):
        return None
    attivi = Dipendente.objects.filter(azienda=azienda, attivo=True)
    trovato = attivi.filter(badge=codice).first()                     # prima il badge esatto
    if trovato is None and codice.isdigit():                            # poi il PIN
        trovato = attivi.filter(pin_impronta=impronta_pin(codice)).first()
    if trovato is None:
        cache.set(f"personale.chiosco:{chiave_chiosco}", cache.get(f"personale.chiosco:{chiave_chiosco}", 0) + 1, BLOCCO_MINUTI * 60)
    else:
        cache.delete(f"personale.chiosco:{chiave_chiosco}")
    return trovato


def ultima(dipendente):
    return dipendente.timbrature.order_by("-il").first()


def prossimo_verso(dipendente):
    """Uscita se l'ultima timbratura di oggi è un'entrata, altrimenti entrata."""
    u = ultima(dipendente)
    if u and u.verso == Timbratura.ENTRATA and timezone.localtime(u.il).date() == timezone.localdate():
        return Timbratura.USCITA
    return Timbratura.ENTRATA


def timbra(dipendente, verso=None, fonte="chiosco", utente=None, il=None, nota=""):
    return Timbratura.objects.create(azienda=dipendente.azienda, dipendente=dipendente, verso=verso or prossimo_verso(dipendente),
                                     fonte=fonte, inserita_da=utente, il=il or timezone.now(), nota=nota[:200])


def _ore(da, a):
    return Decimal((a - da).total_seconds() / 3600).quantize(Decimal("0.01"))


def giornata(dipendente, giorno, timbrature=None, assenze=None):
    """{giorno, lavorate, previste, assenza, ore_assenza, differenza, anomalia, timbrature}"""
    if timbrature is None:
        timbrature = list(dipendente.timbrature.filter(il__date=giorno).order_by("il"))
    if assenze is None:
        assenze = list(dipendente.assenze.filter(stato=Assenza.APPROVATA, dal__lte=giorno, al__gte=giorno).select_related("tipo"))
    lavorate, aperta, anomalie = Decimal(0), None, []
    for t in sorted(timbrature, key=lambda t: t.il):
        if t.verso == Timbratura.ENTRATA:
            if aperta is not None:
                anomalie.append("due entrate di seguito")
            aperta = t.il
        else:
            if aperta is None:
                anomalie.append("uscita senza entrata")
            else:
                lavorate += _ore(aperta, t.il)
                aperta = None
    if aperta is not None and giorno < timezone.localdate():
        anomalie.append("manca l'uscita")
    lavorativo = calendario_lavoro.lavorativo(giorno)
    previste = dipendente.ore_al_giorno if lavorativo else Decimal(0)
    ore_assenza = Decimal(0)
    nomi = []
    for a in assenze:
        nomi.append(str(a.tipo))
        ore_assenza += a.ore if a.ore else previste
    previste_nette = max(previste - ore_assenza, Decimal(0))
    if lavorativo and not timbrature and not assenze and giorno < timezone.localdate():
        anomalie.append("nessuna timbratura")
    return {"giorno": giorno, "lavorativo": lavorativo, "lavorate": lavorate, "previste": previste_nette.quantize(Decimal("0.01")),
            "assenza": ", ".join(nomi), "ore_assenza": ore_assenza.quantize(Decimal("0.01")),
            "differenza": (lavorate - previste_nette).quantize(Decimal("0.01")), "anomalia": "; ".join(anomalie),
            "timbrature": timbrature}


def mese(dipendente, anno, numero):
    primo = datetime.date(anno, numero, 1)
    ultimo = (primo + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    tutte = list(dipendente.timbrature.filter(il__date__gte=primo, il__date__lte=ultimo))
    assenze = list(dipendente.assenze.filter(stato=Assenza.APPROVATA, dal__lte=ultimo, al__gte=primo).select_related("tipo"))
    giorni = []
    d = primo
    while d <= ultimo:
        if d < dipendente.data_assunzione or (dipendente.data_cessazione and d > dipendente.data_cessazione):
            d += datetime.timedelta(days=1)
            continue
        giorni.append(giornata(dipendente, d, [t for t in tutte if timezone.localtime(t.il).date() == d],
                               [a for a in assenze if a.dal <= d <= a.al]))
        d += datetime.timedelta(days=1)
    return giorni


def riepilogo(azienda, anno, numero):
    """[{dipendente, lavorate, previste, differenza, giorni_assenza, anomalie, giorni}] dei dipendenti attivi."""
    righe = []
    for dip in Dipendente.objects.filter(azienda=azienda, attivo=True).order_by("cognome", "nome"):
        giorni = mese(dip, anno, numero)
        righe.append({"dipendente": dip, "giorni": giorni,
                      "lavorate": sum((g["lavorate"] for g in giorni), Decimal(0)),
                      "previste": sum((g["previste"] for g in giorni), Decimal(0)),
                      "differenza": sum((g["differenza"] for g in giorni), Decimal(0)),
                      "giorni_assenza": sum(1 for g in giorni if g["assenza"]),
                      "anomalie": sum(1 for g in giorni if g["anomalia"])})
    return righe


def esporta(azienda, anno, numero):
    """Il file Excel per il consulente del lavoro: una riga per dipendente e giorno."""
    from core.esporta import xlsx_bytes
    intestazioni = ["Dipendente", "Codice fiscale", "Data", "Lavorativo", "Ore lavorate", "Ore previste", "Assenza", "Ore di assenza",
                    "Differenza", "Anomalie", "Timbrature"]
    righe = []
    for r in riepilogo(azienda, anno, numero):
        d = r["dipendente"]
        for g in r["giorni"]:
            righe.append([str(d), d.codice_fiscale, g["giorno"].strftime("%d/%m/%Y"), "sì" if g["lavorativo"] else "no",
                          float(g["lavorate"]), float(g["previste"]), g["assenza"], float(g["ore_assenza"]), float(g["differenza"]),
                          g["anomalia"], " ".join(f"{t.get_verso_display()[0]} {timezone.localtime(t.il):%H:%M}" for t in g["timbrature"])])
    return xlsx_bytes(intestazioni, righe, f"Presenze {numero:02d}-{anno}")
