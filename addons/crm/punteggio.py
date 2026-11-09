"""Punteggio predittivo delle opportunità: la probabilità di vincere stimata dallo storico delle vinte e perse
dell'azienda (bayesiano ingenuo con lisciatura), con i fattori che pesano di più per spiegarla.

Fattori: origine, commerciale, team, fascia di valore, contatto già cliente, email e telefono presenti,
attività registrate (note, messaggi, attività pianificate) ed etichette. Con meno di MINIMO trattative chiuse
il punteggio resta vuoto."""
import math
from collections import Counter

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.utils import timezone

from core.models import AttivitaPianificata, Messaggio

from .models import Opportunita

MINIMO = 10
STORICO_ANNI = 3


def _fascia_valore(v):
    v = float(v or 0)
    if v <= 0:
        return "non indicato"
    for limite, nome in ((1000, "fino a 1.000 €"), (10000, "1.000-10.000 €"), (50000, "10.000-50.000 €")):
        if v <= limite:
            return nome
    return "oltre 50.000 €"


def _fascia_attivita(n):
    return "nessuna" if n == 0 else "1-2" if n <= 2 else "3-5" if n <= 5 else "più di 5"


def _attivita(ids):
    ct = ContentType.objects.get_for_model(Opportunita)
    conta = Counter()
    for oid, n in (Messaggio.objects.filter(content_type=ct, object_id__in=ids, tipo__in=[Messaggio.NOTA, Messaggio.MESSAGGIO])
                   .values_list("object_id").annotate(n=Count("pk"))):
        conta[oid] += n
    for oid, n in AttivitaPianificata.objects.filter(content_type=ct, object_id__in=ids).values_list("object_id").annotate(n=Count("pk")):
        conta[oid] += n
    return conta


def _clienti(azienda_id):
    from contatti.models import Contatto
    return set(Contatto.objects.filter(azienda_id=azienda_id, cliente=True).values_list("pk", flat=True))


def fattori(o, attivita, clienti):
    """[(chiave, etichetta leggibile)] dell'opportunità."""
    origine = (o.origine or "").split(":")[0].strip() or "non indicata"
    voci = [("origine:" + origine.lower(), f"Origine: {origine}"),
            ("commerciale:%s" % o.commerciale_id, f"Commerciale: {o.commerciale.get_full_name() or o.commerciale.username}"
             if o.commerciale_id else "Senza commerciale"),
            ("valore:" + _fascia_valore(o.valore_atteso), f"Valore {_fascia_valore(o.valore_atteso)}"),
            ("cliente:%s" % (o.contatto_id in clienti), "Già cliente" if o.contatto_id in clienti else "Non ancora cliente"),
            ("email:%s" % bool(o.email or (o.contatto_id and o.contatto.email)), "Con email" if o.email or (o.contatto_id and o.contatto.email) else "Senza email"),
            ("telefono:%s" % bool(o.telefono), "Con telefono" if o.telefono else "Senza telefono"),
            ("attivita:" + _fascia_attivita(attivita.get(o.pk, 0)), f"Attività registrate: {_fascia_attivita(attivita.get(o.pk, 0))}")]
    if o.team_id:
        voci.append(("team:%s" % o.team_id, f"Team: {o.team}"))
    voci += [("etichetta:%s" % e.pk, f"Etichetta: {e.nome}") for e in o.etichette.all()]
    return voci


class Modello:
    def __init__(self, vinte, perse, conteggi):
        self.vinte, self.perse, self.conteggi = vinte, perse, conteggi

    @classmethod
    def impara(cls, chiuse, attivita, clienti):
        vinte = perse = 0
        conteggi = {}
        for o in chiuse:
            vinta = o.stato == Opportunita.VINTA
            vinte, perse = vinte + vinta, perse + (not vinta)
            for chiave, _ in fattori(o, attivita, clienti):
                c = conteggi.setdefault(chiave, [0, 0])
                c[0 if vinta else 1] += 1
        return cls(vinte, perse, conteggi)

    def stima(self, voci):
        """(punteggio 0-100, [(etichetta, effetto in punti)] dei fattori più forti)."""
        base = math.log((self.vinte + 1) / (self.perse + 1))
        logit, pesi = base, []
        for chiave, etichetta in voci:
            v, p = self.conteggi.get(chiave, (0, 0))
            if v + p == 0:
                continue                                 # mai visto nello storico: non dice nulla
            peso = math.log((v + 1) / (self.vinte + 2)) - math.log((p + 1) / (self.perse + 2))
            logit += peso
            pesi.append((etichetta, peso))
        prob = 1 / (1 + math.exp(-logit))
        prob_base = 1 / (1 + math.exp(-base))
        # effetto di ciascun fattore in punti: quanto sposta la probabilità partendo dalla media storica
        effetti = [(e, round(100 * (1 / (1 + math.exp(-(base + w))) - prob_base))) for e, w in pesi]
        effetti = sorted((x for x in effetti if x[1]), key=lambda x: -abs(x[1]))[:5]
        return round(100 * prob), effetti


def ricalcola(azienda_id=None):
    """Lavoro periodico: impara dallo storico di ogni azienda e aggiorna il punteggio delle aperte. Restituisce quante."""
    aziende = [azienda_id] if azienda_id else list(Opportunita.objects.values_list("azienda_id", flat=True).distinct())
    dal = timezone.localdate().replace(year=timezone.localdate().year - STORICO_ANNI)
    adesso, aggiornate = timezone.now(), 0
    for az in aziende:
        tutte = Opportunita.objects.filter(azienda_id=az).select_related("commerciale", "team", "contatto").prefetch_related("etichette")
        chiuse = list(tutte.filter(stato__in=[Opportunita.VINTA, Opportunita.PERSA], creata_il__gte=dal))
        aperte = list(tutte.filter(stato=Opportunita.APERTA))
        attivita = _attivita([o.pk for o in chiuse + aperte])
        clienti = _clienti(az)
        if len(chiuse) < MINIMO:
            Opportunita.objects.filter(pk__in=[o.pk for o in aperte]).update(
                punteggio=None, punteggio_fattori=[{"fattore": f"Storico insufficiente: servono almeno {MINIMO} trattative chiuse", "effetto": 0}],
                punteggio_il=adesso)
            continue
        modello = Modello.impara(chiuse, attivita, clienti)
        for o in aperte:
            o.punteggio, effetti = modello.stima(fattori(o, attivita, clienti))
            o.punteggio_fattori, o.punteggio_il = [{"fattore": e, "effetto": p} for e, p in effetti], adesso
        Opportunita.objects.bulk_update(aperte, ["punteggio", "punteggio_fattori", "punteggio_il"], batch_size=500)
        aggiornate += len(aperte)
    return aggiornate
