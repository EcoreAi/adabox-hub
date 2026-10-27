"""Raggruppamenti della lista (?g=campo o campo:mese|anno) e totali dei campi numerici (list_sum)."""
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import Count, F, Sum
from django.db.models.functions import TruncMonth, TruncYear
from django.utils import formats

MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre"]
VUOTO = "—"


def _campo(vista, nome):
    try:
        return vista.opts.get_field(nome)
    except FieldDoesNotExist:
        return None


def _etichetta_campo(f):
    nome = str(f.verbose_name)
    return nome[:1].upper() + nome[1:]


def raggruppabili(vista):
    """[(chiave, etichetta)] dei raggruppamenti ammessi: list_group_by, con 'campo:mese' e 'campo:anno' per le date."""
    risultato = []
    for chiave in vista.list_group_by:
        nome, _, parte = chiave.partition(":")
        f = _campo(vista, nome)
        if f is None or (parte and not isinstance(f, (models.DateField, models.DateTimeField))):
            continue
        risultato.append((chiave, _etichetta_campo(f) + {"": "", "mese": " (mese)", "anno": " (anno)"}.get(parte, "")))
    return risultato


def espressione(vista, chiave):
    nome, _, parte = chiave.partition(":")
    if parte == "mese":
        return TruncMonth(nome)
    if parte == "anno":
        return TruncYear(nome)
    return F(nome)


def etichette(vista, chiave, valori):
    """{valore: etichetta leggibile} per i valori di un raggruppamento."""
    nome, _, parte = chiave.partition(":")
    f = _campo(vista, nome)
    if f.is_relation:
        oggetti = f.related_model._default_manager.in_bulk([v for v in valori if v is not None])
        return {v: str(oggetti.get(v, v)) if v is not None else VUOTO for v in valori}
    scelte = dict(f.flatchoices) if f.choices else {}
    risultato = {}
    for v in valori:
        if v is None or v == "":
            risultato[v] = VUOTO
        elif parte == "mese":
            risultato[v] = f"{MESI[v.month - 1]} {v.year}"
        elif parte == "anno":
            risultato[v] = str(v.year)
        elif isinstance(v, bool):
            risultato[v] = "Sì" if v else "No"
        else:
            risultato[v] = str(scelte.get(v, v))
    return risultato


def numero(valore):
    if valore is None:
        return ""
    if isinstance(valore, float) or hasattr(valore, "quantize"):
        return formats.number_format(valore, decimal_pos=2, use_l10n=True, force_grouping=True)
    return formats.number_format(valore, use_l10n=True, force_grouping=True)


def somme_ammesse(vista):
    return [c for c in vista.list_sum if (f := _campo(vista, c)) is not None
            and isinstance(f, (models.IntegerField, models.DecimalField, models.FloatField))]


def totali(vista, qs):
    """{campo: totale formattato} sull'intero queryset filtrato."""
    campi = somme_ammesse(vista)
    if not campi:
        return {}
    dati = qs.order_by().aggregate(**{f"s_{c}": Sum(c) for c in campi})
    return {c: numero(dati[f"s_{c}"]) for c in campi}


def gruppi(vista, qs, chiave):
    """(qs ordinato per gruppo con l'annotazione _gruppo, {valore: {etichetta, n, somme}})."""
    campi = somme_ammesse(vista)
    annotato = qs.annotate(_gruppo=espressione(vista, chiave))
    righe = (annotato.order_by().values("_gruppo")
             .annotate(_n=Count("pk"), **{f"s_{c}": Sum(c) for c in campi}).order_by("_gruppo"))
    righe = list(righe)
    nomi = etichette(vista, chiave, [r["_gruppo"] for r in righe])
    info = {r["_gruppo"]: {"etichetta": nomi[r["_gruppo"]], "n": r["_n"],
                           "somme": {c: numero(r[f"s_{c}"]) for c in campi}} for r in righe}
    ordine = list(qs.query.order_by) or list(vista.opts.ordering) or ["pk"]
    return annotato.order_by(F("_gruppo").asc(nulls_last=True), *ordine), info
