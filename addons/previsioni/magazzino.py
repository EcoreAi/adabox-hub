"""Magazzino: consumo per periodo, soglie, partenza e proiezione giorno per giorno fino alle date di esaurimento e di
riordino. Le funzioni sul database importano i modelli di Magazzino, Prodotti e Acquisti solo quando servono (il modulo
non dipende da nessuno); `proietta` è pura."""
import calendar
import datetime
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from django.apps import apps
from django.db.models import Min, Sum
from django.utils import timezone

Chiave = tuple[int, int | None]          # (prodotto, magazzino); None = azienda intera

MESI_DI_STORIA = 12
PERIODI_SUGGERITI = {"mese": 3, "settimana": 13}       # «i tre mesi successivi»


# ---- consumo ---------------------------------------------------------------------------------------------------

def _inizio_periodo(giorno, per):
    return giorno.replace(day=1) if per == "mese" else giorno - datetime.timedelta(days=giorno.weekday())


def _giorno_locale(data):
    return timezone.localtime(data).date() if timezone.is_aware(data) else data.date()


def _consumo_documenti(documenti):
    """{periodo: quantità} dei documenti in uscita (consegne): somma netta dei loro movimenti, contata nel periodo del
    primo scarico. Un documento che comincia con un carico (ricevimento) non consuma: i suoi scarichi sono storni."""
    for movimenti in documenti:
        if movimenti[0][0] >= 0:
            continue
        netto = -sum(q for q, _ in movimenti)
        yield movimenti[0][1], max(netto, 0)


def _trasferimenti_interni(azienda):
    """Pk delle uscite di trasferimento il cui arrivo è nello stesso magazzino (cambio di ubicazione). L'uscita si
    abbina al primo arrivo successivo (pk maggiore) con stesso prodotto, lotto, causale e quantità opposta, una volta
    sola; senza abbinamento non è interna (conta come consumo, per prudenza)."""
    from magazzino.models import Movimento

    arrivi = defaultdict(list)
    uscite = []
    for pk, prodotto, magazzino, lotto, causale, q in (Movimento.objects.filter(azienda=azienda, tipo=Movimento.TRASFERIMENTO)
                                                       .order_by("pk").values_list("pk", "prodotto", "magazzino", "lotto", "causale", "quantita")):
        if q < 0:
            uscite.append((pk, magazzino, (prodotto, lotto, causale, -q)))
        else:
            arrivi[(prodotto, lotto, causale, q)].append((pk, magazzino))
    interne = set()
    for pk, magazzino, chiave in uscite:
        candidati = arrivi[chiave]
        for i, (pk_arrivo, magazzino_arrivo) in enumerate(candidati):
            if pk_arrivo > pk:
                del candidati[i]
                if magazzino_arrivo == magazzino:
                    interne.add(pk)
                break
    return interne


def consumi(azienda, per: str) -> dict[Chiave, dict[datetime.date, float]]:
    """Le uscite per periodo, per (prodotto, magazzino) e per (prodotto, None), dei prodotti con uscite."""
    from django.contrib.contenttypes.models import ContentType
    from magazzino.models import Inventario, Movimento

    ct_inventario = ContentType.objects.get_for_model(Inventario).pk
    interne = _trasferimenti_interni(azienda)
    liberi = defaultdict(lambda: defaultdict(Decimal))       # chiave -> periodo -> uscite senza documento
    documenti = defaultdict(list)                            # (chiave, ct, oggetto) -> [(quantità, giorno)]
    qs = (Movimento.objects.filter(azienda=azienda).order_by("data", "pk")
          .values_list("pk", "prodotto", "magazzino", "tipo", "quantita", "data", "causale", "content_type", "object_id"))
    for pk, prodotto, magazzino, tipo, q, data, causale, ct, oggetto in qs.iterator():
        giorno = _giorno_locale(data)
        for chiave in ((prodotto, magazzino), (prodotto, None)):
            if tipo == Movimento.TRASFERIMENTO:
                uscita = q < 0 and chiave[1] is not None and pk not in interne
            elif tipo == Movimento.SCARICO:
                uscita = True
            elif tipo == Movimento.CARICO:
                uscita = False
            else:       # rettifica: conta se negativa e non è un inventario
                uscita = q < 0 and ct != ct_inventario and causale != "Inventario iniziale"
            if tipo in (Movimento.SCARICO, Movimento.CARICO) and ct is not None:
                documenti[(chiave, ct, oggetto)].append((q, giorno))
            elif uscita:
                liberi[chiave][_inizio_periodo(giorno, per)] += -q
    risultato = defaultdict(lambda: defaultdict(Decimal))
    for chiave, periodi in liberi.items():
        for periodo, q in periodi.items():
            risultato[chiave][periodo] += q
    raggruppati = defaultdict(list)
    for (chiave, _, _), movimenti in documenti.items():
        raggruppati[chiave].append(movimenti)
    for chiave, docs in raggruppati.items():
        for giorno, q in _consumo_documenti(docs):
            risultato[chiave][_inizio_periodo(giorno, per)] += q
    return {chiave: {p: max(float(q), 0.0) for p, q in periodi.items()} for chiave, periodi in risultato.items()}


# ---- soglie, partenza, storia ----------------------------------------------------------------------------------

def chiavi_e_soglie(azienda) -> dict[Chiave, tuple[Decimal | None, Decimal | None]]:
    """(riordina sotto, riporta a) per chiave: per magazzino dove c'è una `ScortaMagazzino`; per gli altri prodotti con
    movimenti il totale, con la regola di Acquisti se c'è, altrimenti la scorta minima."""
    from magazzino.models import Movimento, ScortaMagazzino
    from prodotti.models import Prodotto

    soglie = {}
    con_scorta = set()
    for sc in ScortaMagazzino.objects.filter(azienda=azienda):
        soglie[(sc.prodotto_id, sc.magazzino_id)] = (sc.punto_riordino, sc.scorta_obiettivo)
        con_scorta.add(sc.prodotto_id)
    regole = {}
    if apps.is_installed("acquisti"):
        from acquisti.models import RegolaRiordino
        regole = {r.prodotto_id: (r.punto_riordino, r.scorta_obiettivo) for r in RegolaRiordino.objects.filter(azienda=azienda)}
    movimentati = set(Movimento.objects.filter(azienda=azienda).values_list("prodotto", flat=True).distinct())
    minime = dict(Prodotto.objects.filter(azienda=azienda, pk__in=movimentati - con_scorta).values_list("pk", "scorta_minima"))
    for prodotto, minima in minime.items():
        soglie[(prodotto, None)] = regole.get(prodotto) or (minima or None, None)
    return soglie


def partenze(azienda) -> dict[Chiave, Decimal]:
    """Giacenza + in arrivo − impegnato, per magazzino e sul totale."""
    from magazzino.models import Movimento, impegni_e_arrivi

    valori = defaultdict(Decimal)
    for prodotto, magazzino, t in (Movimento.objects.filter(azienda=azienda).values_list("prodotto", "magazzino")
                                   .annotate(t=Sum("quantita"))):
        valori[(prodotto, magazzino)] += t
    impegni, arrivi = impegni_e_arrivi(azienda)
    for chiave, q in arrivi.items():
        valori[chiave] += q
    for chiave, q in impegni.items():
        valori[chiave] -= q
    totali = defaultdict(Decimal)
    for (prodotto, _), q in valori.items():
        totali[(prodotto, None)] += q
    return {**valori, **totali}


def per_della_storia(azienda) -> str:
    """«mese» se dal primo movimento dell'azienda sono passati almeno 12 mesi, altrimenti «settimana»."""
    from magazzino.models import Movimento

    primo = Movimento.objects.filter(azienda=azienda).aggregate(p=Min("data"))["p"]
    if primo is None:
        return "settimana"
    primo, oggi = _giorno_locale(primo), timezone.localdate()
    mesi = (oggi.year - primo.year) * 12 + oggi.month - primo.month - (1 if oggi.day < primo.day else 0)
    return "mese" if mesi >= MESI_DI_STORIA else "settimana"


# ---- proiezione ------------------------------------------------------------------------------------------------

def _periodi(primo_periodo, per, quanti):
    """[(primo giorno, giorni)] dei `quanti` periodi dal primo."""
    periodi, inizio = [], primo_periodo
    for _ in range(quanti):
        giorni = calendar.monthrange(inizio.year, inizio.month)[1] if per == "mese" else 7
        periodi.append((inizio, giorni))
        inizio += datetime.timedelta(days=giorni)
    return periodi


def _giorno_in_cui(partenza, giornaliero, giorni, oggi, scende):
    """Il primo giorno (da `oggi` compreso) la cui giacenza a fine giornata soddisfa `scende`, e quella giacenza."""
    giacenza = partenza
    for giorno, consumo in zip(giorni, giornaliero):
        giacenza -= consumo
        if scende(giacenza):
            return giorno, giacenza
    return None, None


def _fraction(valore):
    return Fraction(str(valore))


def proietta(partenza, futuro: list[tuple[float, float, float]], per, primo_periodo: datetime.date, riordina_sotto, riporta_a,
             oggi: datetime.date) -> dict:
    """Giorno per giorno da `oggi`: la giacenza a fine giornata è la partenza meno il consumo previsto (quantile del
    periodo ripartito sui suoi giorni di calendario). `futuro[0]` è il periodo corrente, che comincia in `primo_periodo`.
    Esaurimento = primo giorno a giacenza ≤ 0 (mediana; `_da` col quantile 90, `_a` col 10); riordino = primo giorno a
    giacenza < `riordina_sotto`. Le date oltre l'ultimo periodo sono None. Calcolo esatto con le frazioni."""
    partenza = _fraction(partenza)
    soglia = _fraction(riordina_sotto) if riordina_sotto is not None and riordina_sotto > 0 else None
    periodi = _periodi(primo_periodo, per, len(futuro))
    giorni_per_periodo = []
    for inizio, durata in periodi:
        giorni_per_periodo.append([inizio + datetime.timedelta(days=i) for i in range(durata)])
    giorni = [g for blocco in giorni_per_periodo for g in blocco if g >= oggi]
    indice = {g: i for i, blocco in enumerate(giorni_per_periodo) for g in blocco}

    def serie(quantile):
        return [max(_fraction(futuro[indice[g]][quantile]), 0) / periodi[indice[g]][1] for g in giorni]

    mediana = serie(1)
    finale = {"esaurimento": None, "esaurimento_da": None, "esaurimento_a": None, "riordino": None,
              "quantita_suggerita": None, "stato": "ok"}
    if partenza <= 0:
        finale["stato"] = "finito"
    for chiave, quantile in (("esaurimento", 1), ("esaurimento_da", 2), ("esaurimento_a", 0)):
        finale[chiave], _ = _giorno_in_cui(partenza, serie(quantile), giorni, oggi, lambda g: g <= 0)
    if soglia is not None:
        finale["riordino"], residua = _giorno_in_cui(partenza, mediana, giorni, oggi, lambda g: g < soglia)
        if finale["riordino"] is not None:
            finale["quantita_suggerita"] = _suggerita(residua, riporta_a, futuro, indice[finale["riordino"]], per)
    if finale["stato"] == "finito":
        return finale
    if soglia is not None and partenza < soglia:
        finale["stato"] = "riordina_ora"
    elif all(m <= 0 for m in mediana):
        finale.update(esaurimento=None, esaurimento_da=None, esaurimento_a=None, riordino=None, quantita_suggerita=None,
                      stato="nessun_consumo")
    elif finale["riordino"] is None and finale["esaurimento"] is None:
        finale["stato"] = "oltre"
    return finale


def _suggerita(giacenza, riporta_a, futuro, periodo, per):
    """Quanto ordinare nel giorno di riordino: fino a «riporta a», altrimenti il consumo mediano dei periodi che
    seguono (tre mesi: 3 mesi o 13 settimane), None se l'orizzonte è finito."""
    if riporta_a is not None:
        valore = _fraction(riporta_a) - giacenza
    else:
        seguenti = futuro[periodo + 1:periodo + 1 + PERIODI_SUGGERITI[per]]
        if not seguenti:
            return None
        valore = sum(max(_fraction(f[1]), 0) for f in seguenti)
    millesimi = Decimal(valore.numerator) / Decimal(valore.denominator)
    return millesimi.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
