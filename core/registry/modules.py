"""Scoperta dei moduli su disco, ordinamento per dipendenze, stati e sincronizzazione con il DB."""
import heapq
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db import transaction

from core.models import Modulo

from . import bootstrap
from .manifest import Manifest, ManifestNonValido, leggi, versione_tupla


@dataclass
class InfoModulo:
    slug: str
    cartella: Path
    manifest: Manifest | None = None
    errore: str | None = None


def scopri(addons_dir=None) -> dict[str, InfoModulo]:
    """Tutte le cartelle di ADDONS_DIR con un __manifest__.py, valido o no."""
    radice = Path(addons_dir or settings.ADDONS_DIR)
    info = {}
    if not radice.is_dir():
        return info
    for cartella in sorted(radice.iterdir()):
        if not (cartella / "__manifest__.py").is_file():
            continue
        try:
            info[cartella.name] = InfoModulo(cartella.name, cartella, manifest=leggi(cartella))
        except ManifestNonValido as e:
            info[cartella.name] = InfoModulo(cartella.name, cartella, errore=str(e))
    return info


def dipendenze(slug, info):
    m = info[slug].manifest if slug in info else None
    return list(m.depends) if m else []


def ordina(slugs, info) -> list[str]:
    """Ordine topologico (Kahn) sui depends; stabile per nome a parità. Errore se dipendenza assente o ciclo.
    Le dipendenze presenti su disco ma fuori da `slugs` non vincolano l'ordine."""
    insieme = set(slugs)
    entranti = {s: set() for s in insieme}
    for s in insieme:
        for d in dipendenze(s, info):
            if d not in info:
                raise ManifestNonValido([f"{s}: dipendenza {d!r} assente su disco"])
            if d in insieme:
                entranti[s].add(d)
    pronti = [s for s, deps in entranti.items() if not deps]
    heapq.heapify(pronti)
    ordine = []
    while pronti:
        s = heapq.heappop(pronti)
        ordine.append(s)
        for altro, deps in entranti.items():
            if s in deps:
                deps.discard(s)
                if not deps:
                    heapq.heappush(pronti, altro)
    if len(ordine) != len(insieme):
        restanti = sorted(insieme - set(ordine))
        raise ManifestNonValido([f"ciclo di dipendenze tra: {', '.join(restanti)}"])
    return ordine


def installati() -> list[str]:
    return bootstrap.leggi_stato(settings.ADDONS_DIR)


def _stato_installato(riga, m):
    if riga.versione_installata and versione_tupla(m.version) > versione_tupla(riga.versione_installata):
        return Modulo.DA_AGGIORNARE
    return Modulo.INSTALLATO


@transaction.atomic
def sincronizza() -> list[Modulo]:
    """Allinea le righe Modulo a disco + file di stato; restituisce le righe ordinate per nome."""
    info = scopri()
    stato = installati()
    righe = {r.slug: r for r in Modulo.objects.all()}
    for slug in set(info) | set(stato):
        i = info.get(slug)
        m = i.manifest if i else None
        riga = righe.get(slug) or Modulo(slug=slug, nome=m.name if m else slug)
        if m:
            riga.nome, riga.versione_disponibile, riga.application = m.name, m.version, m.application
        if slug in stato:
            if m is None:
                riga.stato = Modulo.MANCANTE
                if i:
                    riga.ultimo_errore = i.errore
            elif riga.stato != Modulo.ERRORE:
                if not riga.versione_installata:
                    riga.versione_installata = m.version
                riga.stato = _stato_installato(riga, m)
        elif m is None:
            riga.stato, riga.ultimo_errore = Modulo.ERRORE, i.errore
        elif riga.stato != Modulo.ERRORE:
            riga.stato = Modulo.DISPONIBILE
        riga.save()
    Modulo.objects.exclude(slug__in=set(info) | set(stato)).delete()
    return list(Modulo.objects.order_by("nome"))


@lru_cache(maxsize=8)
def _manifests(addons_dir, slugs):
    trovati = {}
    for slug in slugs:
        try:
            trovati[slug] = leggi(Path(addons_dir) / slug)
        except ManifestNonValido:
            pass
    return trovati


def manifests_attivi() -> dict[str, Manifest]:
    """Manifest dei moduli in settings.ADDONS_ATTIVI (cache per processo: non cambiano senza riavvio)."""
    return _manifests(str(settings.ADDONS_DIR), tuple(settings.ADDONS_ATTIVI))
