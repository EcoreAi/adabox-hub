"""Ricerca negli articoli della guida: per parole, con il titolo che conta più del testo."""
import re

from django.db.models import Q

PAROLE_VUOTE = {"con", "che", "per", "non", "dal", "del", "dei", "della", "delle", "nel", "nella", "una", "uno", "gli",
                "come", "perché", "sono", "mio", "mia", "the", "and", "ho", "ma"}


def parole(testo):
    return [p for p in re.findall(r"\w{3,}", (testo or "").lower()) if p not in PAROLE_VUOTE][:12]


def cerca(articoli, testo, quanti=5):
    termini = parole(testo)
    if not termini:
        return []
    filtro = Q()
    for p in termini:
        filtro |= Q(titolo__icontains=p) | Q(corpo__icontains=p)
    trovati = list(articoli.filter(filtro).select_related("categoria")[:200])

    def punti(a):
        titolo, corpo = a.titolo.lower(), a.corpo.lower()
        return sum(3 * (p in titolo) + (p in corpo) for p in termini)
    return sorted(trovati, key=lambda a: (-punti(a), a.titolo))[:quanti]
