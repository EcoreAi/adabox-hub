"""Quello che la banca ha imparato dagli abbinamenti confermati: quale cliente o fornitore paga da un certo IBAN, con un
certo nome della controparte o con una causale che si ripete (es. «SDD ENEL ENERGIA»). Serve a proporre meglio e a dire
perché; non abbina mai da solo: «Abbina i sicuri» guarda solo numero del documento e importo, come prima."""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

from .models import Abbinamento, normalizza_iban

GIORNI = 730                 # si guarda l'ultimo paio d'anni
MINIMO_CAUSALE = 2           # una causale vale solo se si è già ripetuta
VUOTE = {"bonifico", "pagamento", "fattura", "fatt", "saldo", "acconto", "rif", "riferimento", "disposizione", "favore",
         "vostro", "nostro", "ordine", "sepa", "sct", "inst", "srl", "spa", "snc", "sas", "del", "per", "con", "dal", "alla"}


def firma_causale(testo):
    """Le prime parole significative della causale, senza numeri e date: «SDD ENEL ENERGIA 2026/10» → «enel energia sdd»."""
    parole = [p for p in re.findall(r"[^\W\d_]{3,}", (testo or "").lower()) if p not in VUOTE]
    return " ".join(sorted(set(parole[:4])))


def _nome(testo):
    return " ".join(re.findall(r"[^\W\d_]{2,}", (testo or "").lower()))


@dataclass
class Memoria:
    """{chiave: Counter(contatto_pk)} per IBAN, nome della controparte e causale, separati per entrate e uscite."""
    iban: dict = field(default_factory=lambda: defaultdict(Counter))
    nome: dict = field(default_factory=lambda: defaultdict(Counter))
    causale: dict = field(default_factory=lambda: defaultdict(Counter))

    def impara(self, movimento, contatto_pk):
        verso = "+" if movimento.importo > 0 else "-"
        if movimento.iban_controparte:
            self.iban[verso + normalizza_iban(movimento.iban_controparte)][contatto_pk] += 1
        if movimento.controparte.strip():
            self.nome[verso + _nome(movimento.controparte)][contatto_pk] += 1
        if firma := firma_causale(movimento.descrizione):
            self.causale[verso + firma][contatto_pk] += 1

    def indizi(self, movimento, contatto_pk):
        """[(punti, motivo)] di quello che la storia dice di questo movimento e di questa controparte."""
        verso = "+" if movimento.importo > 0 else "-"
        trovati = []
        if movimento.iban_controparte:
            n = self.iban.get(verso + normalizza_iban(movimento.iban_controparte), {}).get(contatto_pk, 0)
            if n:
                trovati.append((40, f"Dallo stesso IBAN già {n} volt{'a' if n == 1 else 'e'}"))
        if movimento.controparte.strip():
            n = self.nome.get(verso + _nome(movimento.controparte), {}).get(contatto_pk, 0)
            if n:
                trovati.append((25, f"Stessa controparte già abbinata {n} volt{'a' if n == 1 else 'e'}"))
        if firma := firma_causale(movimento.descrizione):
            n = self.causale.get(verso + firma, {}).get(contatto_pk, 0)
            if n >= MINIMO_CAUSALE:
                trovati.append((20, f"Causale ricorrente, già abbinata {n} volte"))
        return trovati


def di(azienda):
    """La memoria dell'azienda dagli abbinamenti confermati a scadenze di clienti e fornitori."""
    m = Memoria()
    if azienda is None:
        return m
    da = timezone.localdate() - timedelta(days=GIORNI)
    righe = (Abbinamento.objects.filter(movimento__azienda=azienda, movimento__data__gte=da)
             .select_related("movimento", "incasso__scadenza__fattura", "scadenza_passiva__fattura"))
    for a in righe:
        if a.incasso_id:
            contatto = a.incasso.scadenza.fattura.cliente_id
        elif a.scadenza_passiva_id:
            contatto = a.scadenza_passiva.fattura.fornitore_id
        else:
            continue
        m.impara(a.movimento, contatto)
    return m
