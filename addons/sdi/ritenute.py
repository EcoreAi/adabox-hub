"""Le ritenute d'acconto operate sui fornitori (professionisti, agenti, occasionali): per l'F24 del mese dopo il
pagamento e per la CU dell'anno. Il principio è di cassa: conta quando la fattura si paga, in proporzione a quanto
si paga. Sono dati di partenza per lo studio: la CU e l'F24 li prepara e li trasmette il commercialista."""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q

from .models import FatturaPassiva, ScadenzaPassiva
from .passive import CAMPI_RITENUTA, FatturaNonValida, estrai_p7m, leggi

CENT = Decimal("0.01")
PROVVIGIONI = {"Q", "R", "S", "T", "U"}                   # causali di agenti e intermediari


def codice_tributo(causale, tipo):
    """Il codice tributo dell'F24 per le ritenute: 1038 sulle provvigioni, 1040 sul lavoro autonomo (e il resto)."""
    return "1038" if causale in PROVVIGIONI else "1040"


def aggiorna(qs):
    """Rilegge dal file originale le ritenute delle fatture arrivate prima che si salvassero. Restituisce quante."""
    fatte = 0
    for f in qs.filter(ritenuta_letta=False).only("pk", "nome_file", "originale", "numero", "data"):
        try:
            with f.originale.open("rb") as file:
                contenuto = file.read()
            xml = estrai_p7m(contenuto) if f.nome_file.lower().endswith(".p7m") else contenuto
            doc = next((d for d in leggi(xml)["documenti"] if d["numero"][:20] == f.numero and d["data"] == f.data), None)
        except (FileNotFoundError, ValueError, OSError, FatturaNonValida):
            doc = None
        valori = {c: doc[c] for c in CAMPI_RITENUTA} if doc else {}
        FatturaPassiva.objects.filter(pk=f.pk).update(ritenuta_letta=True, **valori)
        fatte += 1
    return fatte


@dataclass
class Riga:
    """Le ritenute di un fornitore in un mese di pagamento."""
    fornitore: object
    mese: int
    causale: str
    codice: str
    pagato: Decimal = Decimal(0)
    soggetto: Decimal = Decimal(0)
    non_soggetto: Decimal = Decimal(0)
    ritenuta: Decimal = Decimal(0)
    cassa: Decimal = Decimal(0)
    fatture: list = field(default_factory=list)

    @property
    def nome_mese(self):
        from fatturazione.registro import MESI
        return MESI[self.mese - 1]


def operate(fatture_qs, anno, mese=None):
    """[Riga] per fornitore, mese di pagamento e causale: quanto si è pagato nel periodo e la parte di ritenuta che ne
    segue, in proporzione al pagato sul totale da pagare della fattura."""
    aggiorna(fatture_qs)
    scadenze = ScadenzaPassiva.objects.filter(fattura__in=fatture_qs.filter(~Q(ritenuta=0)), pagata=True, pagata_il__year=anno)
    if mese:
        scadenze = scadenze.filter(pagata_il__month=mese)
    righe = {}
    for s in scadenze.select_related("fattura__fornitore").order_by("pagata_il", "pk"):
        f = s.fattura
        da_pagare = sum((x.importo for x in f.scadenze.all()), Decimal(0)) or (f.totale - f.ritenuta)
        quota = (s.importo / da_pagare) if da_pagare else Decimal(1)
        segno = -1 if f.nota_credito else 1
        chiave = (f.fornitore_id, s.pagata_il.month, f.causale_ritenuta)
        r = righe.setdefault(chiave, Riga(f.fornitore, s.pagata_il.month, f.causale_ritenuta or "",
                                          codice_tributo(f.causale_ritenuta, f.tipo_ritenuta)))
        r.pagato += s.importo * segno
        r.soggetto += (f.base_ritenuta * quota).quantize(CENT) * segno
        r.non_soggetto += (max(f.imponibile - f.base_ritenuta - f.contributo_cassa, Decimal(0)) * quota).quantize(CENT) * segno
        r.ritenuta += (f.ritenuta * quota).quantize(CENT) * segno
        r.cassa += (f.contributo_cassa * quota).quantize(CENT) * segno
        if f not in r.fatture:
            r.fatture.append(f)
    return sorted(righe.values(), key=lambda r: (r.mese, r.fornitore.nome.lower(), r.causale))


def per_f24(righe):
    """{(mese, codice tributo): totale} delle ritenute da versare entro il 16 del mese dopo."""
    totali = {}
    for r in righe:
        totali[(r.mese, r.codice)] = totali.get((r.mese, r.codice), Decimal(0)) + r.ritenuta
    return dict(sorted(totali.items()))


def per_cu(righe):
    """[(fornitore, causale, soggetto, non soggetto, ritenuta, cassa)] dell'anno, una riga per fornitore e causale."""
    totali = {}
    for r in righe:
        t = totali.setdefault((r.fornitore.pk, r.causale), [r.fornitore, r.causale, Decimal(0), Decimal(0), Decimal(0), Decimal(0)])
        t[2] += r.soggetto
        t[3] += r.non_soggetto
        t[4] += r.ritenuta
        t[5] += r.cassa
    return sorted((tuple(v) for v in totali.values()), key=lambda t: (t[0].nome.lower(), t[1]))


def _n(valore):
    return f"{valore:.2f}".replace(".", ",")


def foglio(righe):
    """Le righe del CSV per lo studio: una per fornitore, mese di pagamento e causale."""
    from fatturazione.registro import MESI
    testata = ["Mese di pagamento", "Fornitore", "Partita IVA", "Codice fiscale", "Causale CU", "Codice tributo F24", "Pagato",
               "Soggetto a ritenuta", "Non soggetto", "Ritenuta", "Contributo cassa", "Fatture"]
    return [testata] + [[MESI[r.mese - 1], r.fornitore.nome, r.fornitore.partita_iva, r.fornitore.codice_fiscale, r.causale, r.codice,
                         _n(r.pagato), _n(r.soggetto), _n(r.non_soggetto), _n(r.ritenuta), _n(r.cassa),
                         ", ".join(f"{f.numero} del {f.data:%d/%m/%Y}" for f in r.fatture)] for r in righe]
