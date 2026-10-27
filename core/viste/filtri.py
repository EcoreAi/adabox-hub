"""Ricerca (?q=), filtri (?f_<campo>=), ordinamento (?o=) della lista; usati anche dall'API."""
import operator
from functools import reduce

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models
from django.db.models import Q

LIMITE_OPZIONI = 200


def _campo(vista, nome):
    try:
        return vista.opts.get_field(nome)
    except FieldDoesNotExist:
        return None


def _etichetta(f):
    nome = str(f.verbose_name)
    return nome[:1].upper() + nome[1:]


def specifiche(vista, request):
    """Per ogni campo di list_filter: {campo, label, tipo, opzioni, valore} (tipo 'scelta' o 'data')."""
    risultato = []
    for nome in vista.list_filter:
        f = _campo(vista, nome)
        if f is None:
            continue
        spec = {"campo": nome, "label": _etichetta(f), "tipo": "scelta", "opzioni": [],
                "valore": request.GET.get(f"f_{nome}", "")}
        if isinstance(f, models.BooleanField):
            spec["opzioni"] = [("1", "Sì"), ("0", "No")]
        elif f.choices:
            spec["opzioni"] = [(str(k), v) for k, v in f.flatchoices]
        elif f.is_relation:
            qs = f.related_model._default_manager.all()
            azienda = getattr(request, "azienda", None)
            if azienda is not None and any(c.name == "azienda" for c in f.related_model._meta.get_fields()):
                qs = qs.filter(azienda=azienda)
            spec["opzioni"] = [(str(o.pk), str(o)) for o in qs[:LIMITE_OPZIONI]]
        elif isinstance(f, (models.DateField, models.DateTimeField)):
            spec.update(tipo="data", valore=None, da=request.GET.get(f"f_{nome}_da", ""),
                        a=request.GET.get(f"f_{nome}_a", ""))
        else:
            valori = (vista.get_queryset(request).order_by(nome).values_list(nome, flat=True)
                      .distinct()[:LIMITE_OPZIONI])
            spec["opzioni"] = [(str(v), str(v)) for v in valori if v not in (None, "")]
        risultato.append(spec)
    return risultato


def ordinabili(vista):
    return [c for c in vista.list_display
            if (f := _campo(vista, c)) is not None and f.concrete and not f.many_to_many]


def _filtra(qs, **lookup):
    try:
        return qs.filter(**lookup)
    except (ValueError, ValidationError):      # valore non valido nell'URL: filtro ignorato
        return qs


def applica(vista, request, qs, parametri=None):
    """Applica q, f_* e o al queryset. `parametri` default request.GET."""
    p = request.GET if parametri is None else parametri
    q = p.get("q", "").strip()
    if q and vista.search_fields:
        qs = qs.filter(reduce(operator.or_, (Q(**{f"{c}__icontains": q}) for c in vista.search_fields)))
    distinti = False
    for nome in vista.list_filter:
        f = _campo(vista, nome)
        if f is None:
            continue
        if isinstance(f, (models.DateField, models.DateTimeField)):
            lookup = f"{nome}__date" if isinstance(f, models.DateTimeField) else nome
            if da := p.get(f"f_{nome}_da"):
                qs = _filtra(qs, **{f"{lookup}__gte": da})
            if a := p.get(f"f_{nome}_a"):
                qs = _filtra(qs, **{f"{lookup}__lte": a})
            continue
        valore = p.get(f"f_{nome}", "")
        if valore == "":
            continue
        if isinstance(f, models.BooleanField):
            if valore in ("1", "0"):
                qs = qs.filter(**{nome: valore == "1"})
            continue
        qs = _filtra(qs, **{nome: valore})
        distinti = distinti or f.many_to_many
    o = p.get("o", "")
    if o and o.lstrip("-") in ordinabili(vista):
        qs = qs.order_by(o, "pk")
    return qs.distinct() if distinti else qs
