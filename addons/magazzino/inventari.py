"""Inventari e conte cicliche: fotografia del teorico, contato scritto, letto o importato, approvazione con le
rettifiche al costo di magazzino. Nessuna scrittura contabile: il valore delle differenze va allo studio."""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from core import parametri, sequenze
from prodotti.models import Prodotto

from . import costi, lotti
from .models import Inventario, Movimento, RigaInventario


def _teorici(magazzino, ubicazione=None, prodotti=None):
    """{(prodotto_id, lotto_id): quantità} dai movimenti del magazzino (o dell'ubicazione)."""
    qs = Movimento.objects.filter(magazzino=magazzino)
    if ubicazione is not None:
        qs = qs.filter(ubicazione=ubicazione)
    if prodotti is not None:
        qs = qs.filter(prodotto__in=prodotti)
    return {(r["prodotto"], r["lotto"]): r["t"] for r in qs.values("prodotto", "lotto").annotate(t=Sum("quantita"))}


def attuale(riga):
    inv = riga.inventario
    return _teorici(inv.magazzino, inv.ubicazione, [riga.prodotto_id]).get((riga.prodotto_id, riga.lotto_id), Decimal(0))


@transaction.atomic
def crea(azienda, magazzino, utente=None, ubicazione=None, categoria=None, prodotti=None, ciclica=False, note=""):
    inv = Inventario.objects.create(azienda=azienda, magazzino=magazzino, ubicazione=ubicazione, categoria=categoria,
                                    ciclica=ciclica, note=note, creato_da=utente)
    fotografa(inv, prodotti)
    return inv


def fotografa(inv, prodotti=None):
    """Numero e una riga per ogni bene (e lotto) del perimetro: quelli con giacenza e gli altri beni attivi."""
    if not inv.numero:
        inv.numero = sequenze.prossimo("magazzino.inventario", inv.azienda)
        inv.save(update_fields=["numero"])
    beni = Prodotto.objects.filter(azienda=inv.azienda, tipo=Prodotto.BENE, kit=False)
    if inv.categoria_id:
        beni = beni.filter(categoria_id=inv.categoria_id)
    if prodotti is not None:
        beni = beni.filter(pk__in=[p.pk if hasattr(p, "pk") else p for p in prodotti])
    teorici = _teorici(inv.magazzino, inv.ubicazione, beni)
    righe = [RigaInventario(inventario=inv, prodotto_id=p, lotto_id=l, teorico=q) for (p, l), q in teorici.items() if q]
    con_giacenza = {p for (p, _), q in teorici.items() if q}
    righe += [RigaInventario(inventario=inv, prodotto=p, teorico=0) for p in beni.filter(attivo=True).exclude(pk__in=con_giacenza)
              if not lotti.tracciamento(p)]
    RigaInventario.objects.bulk_create(righe)


def _numero(testo):
    testo = (testo or "").strip().replace(",", ".")
    if not testo:
        return None
    try:
        valore = Decimal(testo)
    except InvalidOperation:
        raise ValidationError(f"«{testo}» non è un numero.")
    if valore < 0:
        raise ValidationError("Il contato non può essere negativo.")
    return valore


def scrivi(inventario, valori):
    """{riga_id: testo} dal form della conta: vuoto = non contato."""
    if inventario.stato != Inventario.CONTA:
        raise ValidationError("L'inventario non è più in conta.")
    righe = {r.pk: r for r in inventario.righe.all()}
    for pk, testo in valori.items():
        r = righe.get(pk)
        if r is not None:
            nuovo = _numero(testo)
            if nuovo != r.contato:
                r.contato = nuovo
                r.save(update_fields=["contato"])


def aggiungi_letti(inventario, letture):
    """{prodotto_id: pezzi} dalla lettura dei codici: si sommano al contato (una riga nuova se il prodotto non c'era)."""
    if inventario.stato != Inventario.CONTA:
        raise ValidationError("L'inventario non è più in conta.")
    with transaction.atomic():
        for prodotto_id, q in letture.items():
            righe = list(inventario.righe.filter(prodotto_id=prodotto_id).order_by("pk"))
            if len(righe) > 1:
                raise ValidationError(f"{righe[0].prodotto} ha più lotti: scrivi il contato lotto per lotto nella pagina della conta.")
            r = righe[0] if righe else RigaInventario.objects.create(inventario=inventario, prodotto_id=prodotto_id, teorico=0)
            r.contato = (r.contato or Decimal(0)) + Decimal(q)
            r.save(update_fields=["contato"])


def importa(inventario, contenuto):
    """CSV «codice;quantità» (codice del prodotto o codice a barre, anche di una confezione). Restituisce (letti, scartati)."""
    from prodotti.models import da_codice
    testo = contenuto.decode("utf-8-sig", errors="replace")
    separatore = ";" if testo.count(";") >= testo.count(",") else ","
    letture, scartati = {}, []
    for riga in csv.reader(io.StringIO(testo), delimiter=separatore):
        if len(riga) < 2 or not riga[0].strip():
            continue
        trovato = da_codice(inventario.azienda, riga[0])
        try:
            q = _numero(riga[1])
        except ValidationError:
            q = None
        if trovato is None or q is None:
            if riga[0].strip().lower() not in ("codice", "prodotto"):
                scartati.append(riga[0].strip())
            continue
        prodotto, pezzi = trovato
        letture[prodotto.pk] = letture.get(prodotto.pk, Decimal(0)) + q * pezzi
    with transaction.atomic():
        for prodotto_id, q in letture.items():
            righe = list(inventario.righe.filter(prodotto_id=prodotto_id).order_by("pk"))
            if len(righe) > 1:
                scartati.append(str(righe[0].prodotto))
                continue
            r = righe[0] if righe else RigaInventario.objects.create(inventario=inventario, prodotto_id=prodotto_id, teorico=0)
            r.contato = q
            r.save(update_fields=["contato"])
    return len(letture), scartati


@transaction.atomic
def approva(inventario, utente=None, non_contati_zero=False):
    """Una rettifica per ogni riga contata diversa dalla giacenza di adesso (i movimenti arrivati durante la conta
    contano). Le righe non contate restano come sono, o vanno a zero se richiesto."""
    inventario = Inventario.objects.select_for_update().get(pk=inventario.pk)
    if inventario.stato != Inventario.CONTA:
        raise ValidationError("L'inventario non è in conta.")
    righe = list(inventario.righe.select_related("prodotto", "lotto"))
    if not any(r.contato is not None for r in righe) and not non_contati_zero:
        raise ValidationError("Non hai contato niente.")
    problemi = []
    piano = []
    for r in righe:
        contato = r.contato if r.contato is not None else (Decimal(0) if non_contati_zero else None)
        if contato is None:
            continue
        diff = contato - attuale(r)
        if diff and lotti.tracciamento(r.prodotto) and r.lotto_id is None:
            problemi.append(f"{r.prodotto}: si segue per lotto, conta lotto per lotto")
            continue
        if diff and r.lotto_id and r.lotto.seriale and abs(diff) != 1:
            problemi.append(f"{r.prodotto} {r.lotto.codice}: un seriale vale uno")
            continue
        piano.append((r, contato, diff))
    if problemi:
        raise ValidationError("; ".join(problemi))
    ct = ContentType.objects.get_for_model(Inventario)
    for r, contato, diff in piano:
        costo = costi.costo_corrente(r.prodotto)
        if diff:
            Movimento.objects.create(azienda=inventario.azienda, prodotto=r.prodotto, magazzino=inventario.magazzino,
                                     ubicazione=inventario.ubicazione, lotto=r.lotto, quantita=diff, tipo=Movimento.RETTIFICA,
                                     causale=f"{inventario}", utente=utente, content_type=ct, object_id=inventario.pk,
                                     costo_unitario=costo if diff > 0 else None)
        r.contato, r.rettifica, r.costo_unitario = contato, diff, costo
        r.save(update_fields=["contato", "rettifica", "costo_unitario"])
    inventario.stato, inventario.approvato_da, inventario.approvato_il = Inventario.APPROVATO, utente, timezone.now()
    inventario.save(update_fields=["stato", "approvato_da", "approvato_il"])
    return inventario


def ultima_conta(azienda):
    """{prodotto_id: data dell'ultima conta approvata}."""
    return dict(RigaInventario.objects.filter(inventario__azienda=azienda, inventario__stato=Inventario.APPROVATO, contato__isnull=False)
                .values_list("prodotto").annotate(d=Max("inventario__data")))


def conta_ciclica():
    """Il lavoro settimanale: per ogni azienda con la conta ciclica accesa, un inventario dei N beni contati da più
    tempo (prima quelli mai contati), nel magazzino predefinito. Non ne apre un altro se quello di prima è in conta."""
    from core.models import Azienda

    from .models import Magazzino
    creati = 0
    for azienda in Azienda.objects.filter(attiva=True):
        try:
            quanti = int(parametri.leggi("magazzino.conta_ciclica", azienda) or 0)
        except (KeyError, TypeError, ValueError):
            quanti = 0
        if quanti <= 0 or Inventario.objects.filter(azienda=azienda, ciclica=True, stato=Inventario.CONTA).exists():
            continue
        magazzino = Magazzino.predefinito_per(azienda)
        if magazzino is None:
            continue
        ultime = ultima_conta(azienda)
        beni = [p for p in Prodotto.objects.filter(azienda=azienda, tipo=Prodotto.BENE, kit=False, attivo=True)]
        beni.sort(key=lambda p: (ultime.get(p.pk) is not None, ultime.get(p.pk) or timezone.localdate(), p.nome))
        if beni:
            crea(azienda, magazzino, prodotti=beni[:quanti], ciclica=True, note="Conta ciclica della settimana")
            creati += 1
    return creati
