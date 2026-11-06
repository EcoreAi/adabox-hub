"""Il piano: mette in fila i compiti aperti sulle ore libere delle persone e ne ricava le date. Non scrive nulla.

La coda è per priorità, poi per scadenza; un compito parte dopo quelli che lo bloccano. Le ore rimaste sono le previste
meno quelle già registrate. Più assegnatari si dividono le ore in parti uguali. Un compito con sottocompiti non conta:
contano loro, altrimenti le ore si sommerebbero due volte. Senza stima o senza assegnatario un compito non ha una data, e
va detto invece di indovinarla."""
import datetime
import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Sum

from progetti.models import Compito, Progetto
from timesheet.models import RigaOre

from .models import ORE_GIORNO, QUOTA, Capacita

ORIZZONTE_GIORNI = 730
UN_GIORNO = datetime.timedelta(days=1)
FESTE_FISSE = {(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)}


def pasqua(anno):
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mese, giorno = divmod(h + m - 7 * n + 114, 31)
    return datetime.date(anno, mese, giorno + 1)


def festivo(giorno):
    return (giorno.month, giorno.day) in FESTE_FISSE or giorno == pasqua(giorno.year) + UN_GIORNO


@dataclass
class Voce:
    pk: int | None
    titolo: str
    progetto_id: int
    persone: list
    ore: Decimal
    scadenza: datetime.date | None = None
    alta: bool = False
    bloccanti: set = field(default_factory=set)
    milestone_id: int | None = None
    problema: str = ""
    inizio: datetime.date | None = None
    fine: datetime.date | None = None
    giorni: dict = field(default_factory=dict)          # {(utente, giorno): ore}

    @property
    def in_ritardo(self):
        return bool(self.scadenza and self.fine and self.fine > self.scadenza)

    @property
    def giorni_ritardo(self):
        return (self.fine - self.scadenza).days if self.in_ritardo else 0

    def chiave(self):
        return (0 if self.alta else 1, self.scadenza or datetime.date.max, self.pk or 0)


class Calendario:
    """Le ore utili di ogni persona in ogni giorno, tolte festività e assenze approvate."""

    def __init__(self, azienda):
        self.schede = {c.utente_id: c for c in Capacita.objects.filter(azienda=azienda)}
        self.assenti, self.permessi = defaultdict(set), defaultdict(Decimal)
        if apps.is_installed("personale"):
            from personale.models import Assenza
            for a in Assenza.objects.filter(azienda=azienda, stato=Assenza.APPROVATA).exclude(dipendente__utente=None).select_related("dipendente"):
                utente = a.dipendente.utente_id
                if a.ore:
                    self.permessi[utente, a.dal] += a.ore
                    continue
                giorno = a.dal
                while giorno <= a.al:
                    self.assenti[utente].add(giorno)
                    giorno += UN_GIORNO

    def ore(self, utente, giorno):
        scheda = self.schede.get(utente)
        settimana = giorno.weekday()
        if (settimana == 5 and not (scheda and scheda.sabato)) or (settimana == 6 and not (scheda and scheda.domenica)):
            return Decimal(0)
        if festivo(giorno) or giorno in self.assenti[utente]:
            return Decimal(0)
        ore, quota = (scheda.ore_giorno, scheda.quota) if scheda else (ORE_GIORNO, QUOTA)
        return max(ore - self.permessi[utente, giorno], Decimal(0)) * quota / 100


def _voci(azienda):
    """(da pianificare, senza data): i compiti aperti dei progetti attivi."""
    compiti = (Compito.objects.filter(azienda=azienda, fase__chiusa=False, progetto__stato=Progetto.ATTIVO)
               .prefetch_related("assegnatari", "bloccato_da__fase").order_by("pk"))
    con_figli = set(Compito.objects.filter(azienda=azienda, padre__isnull=False).values_list("padre_id", flat=True))
    lavorate = dict(RigaOre.objects.filter(azienda=azienda, compito__isnull=False).values_list("compito").annotate(t=Sum("ore")))
    voci, senza_data = [], []
    for c in compiti:
        if c.pk in con_figli:
            continue
        persone = sorted(u.pk for u in c.assegnatari.all())
        voce = Voce(c.pk, c.titolo, c.progetto_id, persone, max(c.ore_previste - lavorate.get(c.pk, 0), Decimal(0)), c.scadenza,
                    c.priorita == Compito.ALTA, {b.pk for b in c.bloccato_da.all() if not b.fase.chiusa}, c.milestone_id)
        if not c.ore_previste:
            voce.problema = "Senza stima delle ore"
        elif not persone:
            voce.problema = "Senza assegnatario"
        (senza_data if voce.problema else voci).append(voce)
    return voci, senza_data


def _ordine(voci):
    """Priorità e scadenza, ma mai prima di chi blocca. Un blocco circolare non ferma il piano: restano in fondo, in ordine di coda."""
    presenti = {v.pk: v for v in voci if v.pk is not None}
    attese = {id(v): len(v.bloccanti & presenti.keys()) for v in voci}
    sblocca = defaultdict(list)
    for v in voci:
        for b in v.bloccanti & presenti.keys():
            sblocca[b].append(v)
    pronti = [(v.chiave(), id(v), v) for v in voci if not attese[id(v)]]
    heapq.heapify(pronti)
    fatti = []
    while pronti:
        _, _, v = heapq.heappop(pronti)
        fatti.append(v)
        for dopo in sblocca[v.pk]:
            attese[id(dopo)] -= 1
            if not attese[id(dopo)]:
                heapq.heappush(pronti, (dopo.chiave(), id(dopo), dopo))
    visti = {id(v) for v in fatti}
    return fatti + sorted((v for v in voci if id(v) not in visti), key=Voce.chiave)


def _colloca(voce, partenza, calendario, usate):
    """Riempie le ore libere da `partenza` in poi: un compito bloccato lascia libero il tempo prima, che altri possono usare."""
    if not voce.ore:
        voce.inizio = voce.fine = partenza
        return
    limite = partenza + datetime.timedelta(days=ORIZZONTE_GIORNI)
    parte = voce.ore / len(voce.persone)
    for utente in voce.persone:
        resto, giorno = parte, partenza
        while resto > 0:
            if giorno > limite:
                voce.problema = "Oltre due anni: controlla la capacità di chi lo segue"
                voce.inizio = voce.fine = None
                return
            libere = calendario.ore(utente, giorno) - usate[utente, giorno]
            if libere > 0:
                presa = min(libere, resto)
                usate[utente, giorno] += presa
                voce.giorni[utente, giorno] = presa
                resto -= presa
                voce.inizio = min(voce.inizio or giorno, giorno)
                voce.fine = max(voce.fine or giorno, giorno)
            giorno += UN_GIORNO


@dataclass
class Piano:
    oggi: datetime.date
    voci: list
    senza_data: list
    calendario: Calendario

    def di_progetto(self, pk):
        return [v for v in self.voci if v.progetto_id == pk]

    def per_compito(self):
        return {v.pk: v for v in self.voci + self.senza_data if v.pk is not None}


def calcola(azienda, oggi, in_piu=None):
    """`in_piu`: una Voce ipotetica, per le simulazioni. Nessuna scrittura, sempre."""
    voci, senza_data = _voci(azienda)
    if in_piu:
        voci.append(in_piu)
    calendario, usate, fine_di = Calendario(azienda), defaultdict(Decimal), {}
    piazzate = []
    for voce in _ordine(voci):
        partenza = oggi
        for b in voce.bloccanti:
            if fine_di.get(b):
                partenza = max(partenza, fine_di[b] + UN_GIORNO)
        _colloca(voce, partenza, calendario, usate)
        if voce.problema:
            senza_data.append(voce)
            continue
        piazzate.append(voce)
        if voce.pk is not None:
            fine_di[voce.pk] = voce.fine
    return Piano(oggi, piazzate, senza_data, calendario)


# ---------- le viste sul piano

def _lunedi(giorno):
    return giorno - datetime.timedelta(days=giorno.weekday())


def carico(piano, settimane=8):
    """Per persona e settimana: ore impegnate, ore disponibili, percentuale; e da quando è libera."""
    inizio = _lunedi(piano.oggi)
    colonne = [inizio + datetime.timedelta(weeks=i) for i in range(settimane)]
    impegni = defaultdict(Decimal)
    persone, ultimo, titoli = set(piano.calendario.schede), {}, defaultdict(list)
    for v in piano.voci:
        persone.update(v.persone)
        for (utente, giorno), ore in v.giorni.items():
            settimana = _lunedi(giorno)
            impegni[utente, settimana] += ore
            ultimo[utente] = max(ultimo.get(utente, giorno), giorno)
            if v.pk is not None and v.pk not in {t[0] for t in titoli[utente, settimana]}:
                titoli[utente, settimana].append((v.pk, v.titolo))
    righe = []
    for utente in get_user_model().objects.filter(pk__in=persone).order_by("first_name", "username"):
        celle = []
        for lunedi in colonne:
            giorni = [lunedi + datetime.timedelta(days=i) for i in range(7)]
            disponibili = sum((piano.calendario.ore(utente.pk, g) for g in giorni if g >= piano.oggi), Decimal(0))
            ore = impegni[utente.pk, lunedi]
            celle.append({"ore": ore, "disponibili": disponibili, "titoli": titoli[utente.pk, lunedi],
                          "percentuale": int(ore * 100 / disponibili) if disponibili else 0, "assente": not disponibili})
        righe.append({"utente": utente, "celle": celle, "libera_dal": ultimo[utente.pk] + UN_GIORNO if utente.pk in ultimo else piano.oggi})
    return {"colonne": colonne, "righe": righe}


def avanzamento(azienda, progetto_pk=None, milestone_pk=None):
    """Percentuale di lavoro fatto sulle ore stimate; i compiti padre non contano."""
    compiti = Compito.objects.filter(azienda=azienda).exclude(sottocompiti__isnull=False)
    compiti = compiti.filter(progetto_id=progetto_pk) if progetto_pk else compiti.filter(milestone_id=milestone_pk)
    lavorate = dict(RigaOre.objects.filter(compito__in=compiti).values_list("compito").annotate(t=Sum("ore")))
    totale, fatto = Decimal(0), Decimal(0)
    for c in compiti.select_related("fase"):
        totale += c.ore_previste
        fatto += c.ore_previste if c.fase.chiusa else min(lavorate.get(c.pk, Decimal(0)), c.ore_previste)
    return int(fatto * 100 / totale) if totale else 0


def consegna(piano, voci, senza_data, scadenza):
    """La data prevista di un gruppo di compiti e come si confronta con quella promessa."""
    prevista = max((v.fine for v in voci), default=None)
    ritardo = (prevista - scadenza).days if prevista and scadenza and prevista > scadenza else 0
    margine = (scadenza - prevista).days if prevista and scadenza and prevista <= scadenza else None
    return {"prevista": prevista, "scadenza": scadenza, "ritardo": ritardo, "margine": margine, "compiti": len(voci),
            "senza_data": len(senza_data), "in_ritardo": sum(1 for v in voci if v.in_ritardo)}
