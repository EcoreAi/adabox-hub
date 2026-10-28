"""Giorni lavorativi: esclusi sabato, domenica e le festività nazionali italiane."""
import datetime
from functools import lru_cache

FISSE = [(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)]


def pasqua(anno):
    """Domenica di Pasqua (algoritmo di Meeus/Jones/Butcher, calendario gregoriano)."""
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mese = (h + m - 7 * n + 114) // 31
    giorno = (h + m - 7 * n + 114) % 31 + 1
    return datetime.date(anno, mese, giorno)


@lru_cache(maxsize=64)
def festivita(anno):
    giorni = {datetime.date(anno, m, g) for m, g in FISSE}
    p = pasqua(anno)
    return frozenset(giorni | {p, p + datetime.timedelta(days=1)})


def lavorativo(giorno):
    return giorno.weekday() < 5 and giorno not in festivita(giorno.year)


def giorni_lavorativi(dal, al):
    """Quanti giorni lavorativi dal `dal` al `al` compresi."""
    if dal is None or al is None or al < dal:
        return 0
    return sum(1 for i in range((al - dal).days + 1) if lavorativo(dal + datetime.timedelta(days=i)))
