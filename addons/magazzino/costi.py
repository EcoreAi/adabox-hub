"""Costi di magazzino senza contabilità: costo medio ponderato, FIFO o standard, per prodotto e per azienda (tutti i
magazzini insieme: spostare la merce non ne cambia il costo).

Il valore a una data si ottiene ripercorrendo i movimenti in ordine di data: così resta giusto anche con un movimento
inserito con una data passata. I costi salvati sui movimenti servono a mostrarli e a esportarli; «ricalcola» li
riallinea dopo un movimento retrodatato o un cambio di metodo."""
from collections import deque
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from core import parametri

MEDIO, FIFO, STANDARD = "medio", "fifo", "standard"
METODI = [(MEDIO, "Costo medio ponderato"), (FIFO, "FIFO (primo entrato, primo uscito)"), (STANDARD, "Costo standard del prodotto")]
ZERO = Decimal(0)
Q4, Q2 = Decimal("0.0001"), Decimal("0.01")


def q4(v):
    return Decimal(v).quantize(Q4, rounding=ROUND_HALF_UP)


def q2(v):
    return Decimal(v).quantize(Q2, rounding=ROUND_HALF_UP)


def metodo_azienda(azienda):
    try:
        return parametri.leggi("magazzino.metodo_costo", azienda) or MEDIO
    except KeyError:
        return MEDIO


def metodo(prodotto):
    scelta = getattr(prodotto, "metodo_costo", None)
    return scelta.metodo if scelta is not None and scelta.metodo else metodo_azienda(prodotto.azienda)


@dataclass
class Stato:
    """Quantità e valore di un prodotto mentre si ripercorrono i movimenti."""
    metodo: str
    standard: Decimal
    quantita: Decimal = ZERO
    valore: Decimal = ZERO
    strati: deque = field(default_factory=deque)      # FIFO: [quantità, costo]; quantità negativa = merce uscita senza giacenza
    ultimo: Decimal = None

    @property
    def costo_corrente(self):
        """Il costo a cui uscirebbe ora una unità."""
        if self.metodo == STANDARD:
            return self.standard
        if self.metodo == FIFO:
            for quantita, costo in self.strati:
                if quantita > 0:
                    return costo
        elif self.quantita > 0:
            return q4(self.valore / self.quantita)
        return self.ultimo if self.ultimo is not None else self.standard

    def entra(self, quantita, costo=None):
        costo = q4(costo) if costo is not None else self.costo_corrente
        if self.metodo == STANDARD:
            costo = self.standard
        elif self.metodo == FIFO:
            resto = quantita
            while resto > 0 and self.strati and self.strati[0][0] < 0:       # prima copre la merce uscita in negativo
                coperta = min(resto, -self.strati[0][0])
                self.strati[0][0] += coperta
                resto -= coperta
                if self.strati[0][0] == 0:
                    self.strati.popleft()
            if resto > 0:
                self.strati.append([resto, costo])
        prima = self.quantita
        self.quantita += quantita
        self.ultimo = costo
        if self.metodo == MEDIO and prima < 0:
            self.valore = self.quantita * costo          # la merce uscita in negativo si salda al costo nuovo
        else:
            self._aggiorna_valore(quantita * costo)
        return costo

    def esce(self, quantita):
        """quantita positiva. Restituisce il costo unitario dell'uscita."""
        if self.metodo == FIFO:
            resto, valore = quantita, ZERO
            while resto > 0 and self.strati and self.strati[0][0] > 0:
                presa = min(resto, self.strati[0][0])
                valore += presa * self.strati[0][1]
                self.strati[0][0] -= presa
                resto -= presa
                if self.strati[0][0] == 0:
                    self.strati.popleft()
            if resto > 0:                                                    # giacenza negativa: all'ultimo costo
                costo = self.ultimo if self.ultimo is not None else self.standard
                valore += resto * costo
                self.strati.appendleft([-resto, costo])
            costo = q4(valore / quantita)
        else:
            costo = self.costo_corrente
        self.quantita -= quantita
        self._aggiorna_valore(-quantita * costo)
        return costo

    def _aggiorna_valore(self, differenza):
        if self.metodo == STANDARD:
            self.valore = self.quantita * self.standard
        elif self.metodo == FIFO:
            self.valore = sum((qt * c for qt, c in self.strati), ZERO)
        else:
            self.valore = ZERO if self.quantita == 0 else self.valore + differenza


def ripercorri(prodotto, fino_a=None, movimenti=None):
    """(stato finale, [(movimento, costo unitario)]) ripercorrendo i movimenti del prodotto in ordine di data."""
    from .models import Movimento
    if movimenti is None:
        movimenti = Movimento.objects.filter(prodotto=prodotto).order_by("data", "pk")
        if fino_a is not None:
            movimenti = movimenti.filter(data__lte=fino_a)
    stato = Stato(metodo(prodotto), q4(prodotto.costo or 0))
    costi = []
    for m in movimenti:
        if m.quantita > 0:
            costi.append((m, stato.entra(m.quantita, m.costo_unitario if m.costo_fissato else None)))
        else:
            costi.append((m, stato.esce(-m.quantita)))
    return stato, costi


def costo_corrente(prodotto):
    return ripercorri(prodotto)[0].costo_corrente


def costo_uscita(prodotto, quantita):
    """Il costo unitario di un'uscita fatta adesso (dopo tutti i movimenti esistenti)."""
    stato, _ = ripercorri(prodotto)
    return stato.esce(Decimal(quantita))


@transaction.atomic
def ricalcola(prodotto):
    """Riscrive costo e valore dei movimenti del prodotto. Restituisce quanti ne sono cambiati."""
    from .models import Movimento
    _, costi = ripercorri(prodotto)
    cambiati = 0
    for m, costo in costi:
        valore = q2(m.quantita * costo)
        if m.costo_unitario != costo or m.valore != valore:
            Movimento.objects.filter(pk=m.pk).update(costo_unitario=costo, valore=valore)
            cambiati += 1
    return cambiati


def valorizzazione(prodotti, fino_a=None):
    """[{prodotto, metodo, quantita, costo, valore}] dei prodotti con giacenza diversa da zero alla data."""
    from .models import Movimento
    per_prodotto = {}
    movimenti = Movimento.objects.filter(prodotto__in=prodotti).order_by("data", "pk")
    if fino_a is not None:
        movimenti = movimenti.filter(data__lte=fino_a)
    for m in movimenti:
        per_prodotto.setdefault(m.prodotto_id, []).append(m)
    righe = []
    for p in prodotti:
        if p.pk not in per_prodotto:
            continue
        stato, _ = ripercorri(p, movimenti=per_prodotto[p.pk])
        if stato.quantita == 0:
            continue
        valore = q2(stato.valore)
        righe.append({"prodotto": p, "metodo": stato.metodo, "quantita": stato.quantita,
                      "costo": q4(valore / stato.quantita) if stato.quantita else ZERO, "valore": valore})
    return righe
