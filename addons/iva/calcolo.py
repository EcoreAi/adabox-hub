"""Liquidazione IVA di periodo, senza contabilità: dal registro delle vendite (fatture emesse) e da quello degli
acquisti (fatture ricevute registrate).

Le regole seguite, in breve:
- IVA a debito: le fatture emesse nel periodo, note di credito in negativo. La scissione dei pagamenti (split payment)
  la versa il cliente: non entra. L'esigibilità differita entra quando si incassa, in proporzione, o dopo un anno.
- Autofatture d'integrazione (TD16-TD20, TD28): l'IVA è a debito e insieme a credito, perché va nei due registri.
- IVA a credito: le fatture ricevute registrate nel periodo, per la percentuale detraibile di ciascuna. Le righe in
  inversione contabile (N6) non entrano nel totale degli acquisti: entra l'autofattura che le integra.
- Il debito sotto la soglia minima passa al periodo dopo; il credito passa al periodo dopo nello stesso anno.
- Trimestrali: l'1% di interessi sul dovuto dei primi tre trimestri. Il quarto si versa con la dichiarazione annuale.
"""
import datetime
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q

from core import parametri
from fatturazione.models import Fattura, Incasso
from fiscale.calcoli import arrotonda
from sdi.models import FatturaPassiva, ScadenzaPassiva

from .models import Liquidazione

ZERO = Decimal(0)
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]
INTEGRAZIONE = {"TD16", "TD17", "TD18", "TD19", "TD20", "TD28"}


def nome_periodo(periodicita, periodo):
    return MESI[periodo - 1] if periodicita == Liquidazione.MENSILE else f"{periodo}° trimestre"


def mesi(periodicita, periodo):
    return (periodo,) if periodicita == Liquidazione.MENSILE else tuple(range(3 * periodo - 2, 3 * periodo + 1))


def ultimo_periodo(periodicita):
    return 12 if periodicita == Liquidazione.MENSILE else 4


def periodicita_di(azienda):
    return parametri.leggi("iva.periodicita", azienda) or Liquidazione.MENSILE


def soglia():
    return Decimal(str(parametri.leggi("iva.soglia_versamento") or 100))


def fuori_campo(natura):
    """Escluse e non soggette (N1, N2.x): non sono operazioni da dichiarare nei totali."""
    return bool(natura) and (natura == "N1" or natura.startswith("N2"))


def debito_rinviabile(periodicita, periodo):
    """Le specifiche LIPE non ammettono il debito precedente nel primo e nell'ultimo periodo dell'anno."""
    return periodo not in (1, ultimo_periodo(periodicita))


def scadenza_versamento(anno, periodicita, periodo):
    """(data, codice tributo) del modello F24. Se la data cade di sabato o festivo si va al primo giorno lavorativo."""
    if periodicita == Liquidazione.MENSILE:
        data = datetime.date(anno + (periodo == 12), periodo % 12 + 1, 16)
        return data, f"60{periodo:02d}"
    return {1: (datetime.date(anno, 5, 16), "6031"), 2: (datetime.date(anno, 8, 20), "6032"),
            3: (datetime.date(anno, 11, 16), "6033"), 4: (datetime.date(anno + 1, 3, 16), "6099")}[periodo]


def _un_anno_dopo(data):
    try:
        return data.replace(year=data.year + 1)
    except ValueError:                                     # 29 febbraio
        return data.replace(year=data.year + 1, day=28)


@dataclass
class Voce:
    descrizione: str
    imponibile: Decimal = ZERO
    imposta: Decimal = ZERO
    nota: str = ""


@dataclass
class Calcolo:
    vendite: list = field(default_factory=list)
    acquisti: list = field(default_factory=list)
    attive: Decimal = ZERO                 # VP2
    passive: Decimal = ZERO                # VP3
    esigibile: Decimal = ZERO              # VP4
    detratta: Decimal = ZERO               # VP5
    split: Decimal = ZERO                  # IVA versata dai clienti in scissione dei pagamenti
    differita_incassata: Decimal = ZERO    # IVA differita diventata esigibile nel periodo
    differita_sospesa: Decimal = ZERO      # IVA differita emessa nel periodo, non ancora esigibile
    indetraibile: Decimal = ZERO
    integrazione: Decimal = ZERO           # IVA delle autofatture, a debito e a credito
    documenti_vendite: int = 0
    documenti_acquisti: int = 0


def _vendite(azienda, anno, mesi_periodo, c):
    voci = OrderedDict()
    fatture = (Fattura.objects.filter(azienda=azienda, stato=Fattura.EMESSA, data__year=anno, data__month__in=mesi_periodo)
               .prefetch_related("righe__aliquota", "casse__aliquota"))
    for f in fatture:
        c.documenti_vendite += 1
        for g in f.riepilogo_iva():
            a, imponibile, imposta = g["aliquota"], g["imponibile"] * f.segno, g["imposta"] * f.segno
            if not fuori_campo(a.natura):
                c.attive += imponibile
            voce = voci.setdefault(a.pk, Voce(a.descrizione))
            voce.imponibile += imponibile
            voce.imposta += imposta
            if a.esigibilita == a.SCISSIONE:
                c.split += imposta
                voce.nota = "scissione dei pagamenti: la versa il cliente"
            elif a.esigibilita == a.DIFFERITA:
                c.differita_sospesa += imposta
                voce.nota = "esigibilità differita: si versa all'incasso"
            else:
                c.esigibile += imposta
                if f.tipo in INTEGRAZIONE:
                    c.integrazione += imposta
    c.vendite = list(voci.values())


def _iva_differita(fattura):
    return sum((g["imposta"] for g in fattura.riepilogo_iva() if g["aliquota"].esigibilita == g["aliquota"].DIFFERITA), ZERO)


def _differita_esigibile(azienda, anno, mesi_periodo):
    """IVA differita che diventa esigibile nel periodo: la quota degli incassi, o il resto quando è passato un anno."""
    totale = ZERO
    incassi = (Incasso.objects.filter(scadenza__fattura__azienda=azienda, scadenza__fattura__stato=Fattura.EMESSA,
                                      data__year=anno, data__month__in=mesi_periodo,
                                      scadenza__fattura__righe__aliquota__esigibilita="D")
               .distinct().select_related("scadenza__fattura"))
    for i in incassi:
        f = i.scadenza.fattura
        if f.totale and i.data <= _un_anno_dopo(f.data):
            totale += _iva_differita(f) * i.importo / f.totale
    scadute = (Fattura.objects.filter(azienda=azienda, stato=Fattura.EMESSA, data__year=anno - 1, data__month__in=mesi_periodo,
                                      righe__aliquota__esigibilita="D").distinct())
    for f in scadute:
        limite = _un_anno_dopo(f.data)
        if limite.year != anno or limite.month not in mesi_periodo:
            continue
        incassato = sum((i.importo for s in f.scadenze.all() for i in s.incassi.all() if i.data <= limite), ZERO)
        iva = _iva_differita(f)
        totale += iva - (iva * incassato / f.totale if f.totale else ZERO)
    return arrotonda(totale)


def _percentuale(fattura):
    d = getattr(fattura, "detraibilita", None)
    return d.percentuale if d is not None else Decimal(100)


def _acquisti(azienda, anno, mesi_periodo, c):
    voci = OrderedDict()
    fatture = (FatturaPassiva.objects.filter(azienda=azienda, stato=FatturaPassiva.REGISTRATA, registrata_il__year=anno,
                                             registrata_il__month__in=mesi_periodo)
               .select_related("detraibilita").prefetch_related("riepilogo"))
    for f in fatture:
        c.documenti_acquisti += 1
        segno = Decimal(-1) if f.nota_credito else Decimal(1)
        percentuale = _percentuale(f)
        for r in f.riepilogo.all():
            imponibile, imposta = r.imponibile * segno, r.imposta * segno
            if not fuori_campo(r.natura) and not r.natura.startswith("N6"):
                c.passive += imponibile
            chiave = (r.aliquota, r.natura, percentuale)
            nome = f"{r.aliquota:.0f}%" + (f" {r.natura}" if r.natura else "") + (f" · detraibile {percentuale:g}%" if percentuale != 100 else "")
            voce = voci.setdefault(chiave, Voce(nome))
            voce.imponibile += imponibile
            voce.imposta += imposta
            if r.esigibilita == "S":
                voce.nota = "scissione dei pagamenti: non si detrae dal fornitore"
                continue
            if r.esigibilita == "D":
                voce.nota = "esigibilità differita: si detrae quando si paga"
                continue
            detraibile = arrotonda(imposta * percentuale / 100)
            c.detratta += detraibile
            c.indetraibile += imposta - detraibile
    c.acquisti = list(voci.values())


def _differita_pagata(azienda, anno, mesi_periodo):
    totale = ZERO
    scadenze = (ScadenzaPassiva.objects.filter(fattura__azienda=azienda, fattura__stato=FatturaPassiva.REGISTRATA, pagata=True,
                                               pagata_il__year=anno, pagata_il__month__in=mesi_periodo,
                                               fattura__riepilogo__esigibilita="D")
                .distinct().select_related("fattura__detraibilita"))
    for s in scadenze:
        f = s.fattura
        iva = sum((r.imposta for r in f.riepilogo.all() if r.esigibilita == "D"), ZERO)
        if f.totale:
            totale += iva * s.importo / f.totale * _percentuale(f) / 100
    return arrotonda(totale)


def calcola(azienda, anno, periodicita, periodo):
    """Debito e credito del periodo dai registri."""
    c = Calcolo()
    m = mesi(periodicita, periodo)
    _vendite(azienda, anno, m, c)
    c.differita_incassata = _differita_esigibile(azienda, anno, m)
    c.esigibile += c.differita_incassata
    _acquisti(azienda, anno, m, c)
    differita = _differita_pagata(azienda, anno, m)
    c.detratta += differita + c.integrazione
    for nome in ("attive", "passive", "esigibile", "detratta", "split", "differita_sospesa", "indetraibile"):
        setattr(c, nome, arrotonda(getattr(c, nome)))
    return c


CAMPI = ["attive", "passive", "esigibile", "detratta", "iva_dovuta", "iva_credito", "debito_precedente",
         "credito_precedente", "credito_anno_precedente", "versamenti_auto", "crediti_imposta", "interessi", "acconto",
         "da_versare", "a_credito"]


@dataclass
class Risultato:
    anno: int
    periodicita: str
    periodo: int
    calcolo: Calcolo = None
    liquidazione: Liquidazione = None
    numeri: dict = field(default_factory=dict)
    avvisi: list = field(default_factory=list)
    da_chiusura: bool = False

    def __getattr__(self, nome):
        if nome in CAMPI:
            return self.numeri.get(nome, ZERO)
        raise AttributeError(nome)

    @property
    def nome(self):
        return f"{nome_periodo(self.periodicita, self.periodo)} {self.anno}"

    @property
    def scadenza(self):
        return scadenza_versamento(self.anno, self.periodicita, self.periodo)

    @property
    def rinviato(self):
        """Debito sotto la soglia che passa al periodo dopo: in questo periodo non si versa."""
        return (ZERO < self.da_versare < soglia() and self.periodo < ultimo_periodo(self.periodicita)
                and debito_rinviabile(self.periodicita, self.periodo + 1))

    @property
    def da_versare_ora(self):
        return ZERO if self.rinviato else self.da_versare


def _numeri(r):
    return {k: str(v) for k, v in r.numeri.items()}


def liquida(azienda, anno, periodicita, periodo, _cache=None):
    """Il risultato del periodo, con i riporti dal periodo prima. Una liquidazione chiusa dà i numeri salvati."""
    cache = {} if _cache is None else _cache
    if periodo in cache:
        return cache[periodo]
    liq = Liquidazione.objects.filter(azienda=azienda, anno=anno, periodicita=periodicita, periodo=periodo).first()
    r = Risultato(anno, periodicita, periodo, liquidazione=liq)
    if liq and liq.chiusa and liq.dati:
        r.numeri = {k: Decimal(v) for k, v in liq.dati.items()}
        r.da_chiusura = True
        cache[periodo] = r
        return r
    c = r.calcolo = calcola(azienda, anno, periodicita, periodo)
    n = r.numeri
    n.update(attive=c.attive, passive=c.passive, esigibile=c.esigibile, detratta=c.detratta)
    differenza = c.esigibile - c.detratta
    n["iva_dovuta"], n["iva_credito"] = max(differenza, ZERO), max(-differenza, ZERO)
    n["debito_precedente"] = n["credito_precedente"] = ZERO
    if periodo > 1:
        prima = liquida(azienda, anno, periodicita, periodo - 1, cache)
        if prima.rinviato:
            n["debito_precedente"] = prima.da_versare
        n["credito_precedente"] = prima.a_credito
    for nome in ("credito_anno_precedente", "versamenti_auto", "crediti_imposta", "acconto"):
        n[nome] = getattr(liq, nome) if liq else ZERO
    prima_dei_crediti = n["iva_dovuta"] + n["debito_precedente"] - n["credito_precedente"] - n["credito_anno_precedente"] - n["versamenti_auto"]
    if n["crediti_imposta"] > max(prima_dei_crediti - n["iva_credito"], ZERO):
        n["crediti_imposta"] = max(prima_dei_crediti - n["iva_credito"], ZERO)
        r.avvisi.append("I crediti d'imposta superano il dovuto: ne uso solo quanto serve ad azzerarlo.")
    base = prima_dei_crediti - n["iva_credito"] - n["crediti_imposta"]
    n["interessi"] = (arrotonda(base * Decimal("0.01")) if periodicita == Liquidazione.TRIMESTRALE and periodo < 4 and base > 0
                      else ZERO)
    finale = base + n["interessi"] - n["acconto"]
    n["da_versare"], n["a_credito"] = max(finale, ZERO), max(-finale, ZERO)
    cache[periodo] = r
    return r


def anno(azienda, anno, periodicita):
    """Tutti i periodi dell'anno, fino a quello in corso."""
    oggi = datetime.date.today()
    ultimo = ultimo_periodo(periodicita)
    if anno == oggi.year:
        ultimo = oggi.month if periodicita == Liquidazione.MENSILE else (oggi.month - 1) // 3 + 1
    cache = {}
    return [liquida(azienda, anno, periodicita, p, cache) for p in range(1, ultimo + 1)]


def chiudi(azienda, anno_, periodicita, periodo, utente):
    from django.utils import timezone
    r = liquida(azienda, anno_, periodicita, periodo)
    liq, _ = Liquidazione.objects.get_or_create(azienda=azienda, anno=anno_, periodicita=periodicita, periodo=periodo)
    liq.dati, liq.chiusa, liq.chiusa_il, liq.chiusa_da = _numeri(r), True, timezone.now(), utente
    liq.save()
    return liq


def cambiati(r):
    """Per una liquidazione chiusa: i registri dicono ancora le stesse cifre? Restituisce le differenze."""
    if not r.da_chiusura:
        return []
    c = calcola(r.liquidazione.azienda, r.anno, r.periodicita, r.periodo)
    return [(etichetta, r.numeri.get(nome, ZERO), getattr(c, nome))
            for nome, etichetta in (("esigibile", "IVA a debito"), ("detratta", "IVA detratta"))
            if r.numeri.get(nome, ZERO) != getattr(c, nome)]


def bollo_trimestre(azienda, anno, trimestre):
    """Imposta di bollo delle fatture elettroniche del trimestre, da versare con F24 (codici 2521-2524)."""
    fatture = Fattura.objects.filter(azienda=azienda, stato=Fattura.EMESSA, data__year=anno,
                                     data__month__in=mesi(Liquidazione.TRIMESTRALE, trimestre)).filter(~Q(bollo=0))
    scadenze = {1: datetime.date(anno, 5, 31), 2: datetime.date(anno, 9, 30), 3: datetime.date(anno, 11, 30),
                4: datetime.date(anno + 1, 2, 28)}
    return {"trimestre": trimestre, "numero": fatture.count(), "importo": sum((f.bollo for f in fatture), ZERO),
            "codice": f"252{trimestre}", "scadenza": scadenze[trimestre]}
