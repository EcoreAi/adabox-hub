"""Cosa si può mettere in ogni attributo di una vista, e validazione/pulizia di una personalizzazione."""
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from core.models import CampoPersonalizzato

LISTE = ("list_display", "list_filter", "search_fields", "list_group_by", "list_sum", "ordering", "kanban_fields")
NUMERICI = (models.IntegerField, models.DecimalField, models.FloatField)
DATE = (models.DateField, models.DateTimeField)


def originale(vista):
    return getattr(vista, "originale", vista)


def _campi(vista):
    return [f for f in vista.opts.get_fields() if getattr(f, "concrete", False) and f.name != "proprieta"]


def _prop(vista):
    if not any(f.name == "proprieta" for f in vista.opts.get_fields()):
        return []
    tipo = ContentType.objects.get_for_model(vista.model)
    visti, risultato = set(), []
    for c in CampoPersonalizzato.objects.filter(modello=tipo).order_by("ordine", "pk"):
        if c.nome not in visti:
            visti.add(c.nome)
            risultato.append((f"prop_{c.nome}", c.label))
    return risultato


def _metodi_colonna(vista):
    return [n[4:] for n in dir(type(originale(vista))) if n.startswith("col_") and n != "col_valore"]


def valori_originali(vista):
    """Gli attributi personalizzabili come li dichiara il modulo (liste JSON)."""
    v = originale(vista)
    return {
        **{a: list(getattr(v, a) or ()) for a in LISTE},
        "per_page": v.per_page,
        "form_layout": [[titolo, [list(r) for r in righe]] for titolo, righe in v.layout()],
        "etichette": dict(v.etichette),
    }


def disponibili(vista):
    """{attributo: [(nome, etichetta)]} delle scelte ammesse; comprende sempre i valori originali."""
    v = originale(vista)
    et = v.etichetta
    campi = _campi(v)
    prop = _prop(v)
    colonne = [("__str__", et("__str__"))] + [(f.name, et(f.name)) for f in campi if not f.many_to_many]
    colonne += [(n, et(n)) for n in _metodi_colonna(v) if n not in {c for c, _ in colonne}] + prop
    filtri = [(f.name, et(f.name)) for f in campi if isinstance(f, (models.BooleanField, *DATE))
              or f.choices or (f.is_relation and f.many_to_one)]
    gruppi = []
    for f in campi:
        if isinstance(f, DATE):
            gruppi += [(f"{f.name}:mese", f"{et(f.name)} (mese)"), (f"{f.name}:anno", f"{et(f.name)} (anno)")]
        elif isinstance(f, models.BooleanField) or f.choices or (f.is_relation and f.many_to_one):
            gruppi.append((f.name, et(f.name)))
    ricerca = [(f.name, et(f.name)) for f in campi if isinstance(f, (models.CharField, models.TextField))]
    form = [(f.name, et(f.name)) for f in campi if not f.auto_created and f.name != v.company_field
            and (f.editable or f.name in v.readonly_fields)] + prop
    if prop:
        form.append(("@proprieta", "Tutti i campi personalizzati"))
    risultato = {
        "list_display": colonne, "list_filter": filtri, "search_fields": ricerca, "list_group_by": gruppi,
        "list_sum": [(f.name, et(f.name)) for f in campi if isinstance(f, NUMERICI)],
        "ordering": [(f.name, et(f.name)) for f in campi if not f.many_to_many],
        "kanban_fields": [c for c in colonne if c[0] != "__str__"],
        "form": form,
    }
    originali = valori_originali(v)
    for attributo in LISTE:                                   # i valori del modulo restano sempre ammessi
        presenti = {n for n, _ in risultato[attributo]}
        for nome in originali[attributo]:
            base = nome.lstrip("-")
            if base not in presenti:
                risultato[attributo].append((base, et(base.split("__")[0].split(":")[0]) if "__" not in base else base))
                presenti.add(base)
    presenti = {n for n, _ in risultato["form"]}
    for _, righe in originali["form_layout"]:
        for riga in righe:
            for nome in riga:
                if nome not in presenti:
                    risultato["form"].append((nome, et(nome)))
                    presenti.add(nome)
    return risultato


def obbligatori(vista):
    """Campi del form originale che il form non può perdere (richiesti, senza default)."""
    v = originale(vista)
    nel_form = {c for _, righe in valori_originali(v)["form_layout"] for r in righe for c in r}
    risultato = []
    for nome in nel_form:
        try:
            f = v.opts.get_field(nome)
        except FieldDoesNotExist:
            continue
        if (getattr(f, "editable", False) and not f.blank and not f.has_default() and nome not in v.readonly_fields
                and not f.auto_created):
            risultato.append(nome)
    return sorted(risultato)


def _ammessi(disp, attributo):
    return {n for n, _ in disp["form" if attributo == "form_layout" else attributo]}


def pulisci(vista, dati):
    """Solo i valori ancora validi (un aggiornamento del modulo può aver tolto un campo)."""
    if not dati:
        return {}
    disp = disponibili(vista)
    risultato = {}
    for attributo in LISTE:
        if attributo in dati and isinstance(dati[attributo], list):
            ammessi = _ammessi(disp, attributo)
            risultato[attributo] = [n for n in dati[attributo] if isinstance(n, str) and n.lstrip("-") in ammessi]
    if not risultato.get("list_display", True):
        del risultato["list_display"]
    if isinstance(dati.get("per_page"), int) and 10 <= dati["per_page"] <= 500:
        risultato["per_page"] = dati["per_page"]
    if isinstance(dati.get("form_layout"), list) and not originale(vista).form_class:
        ammessi = _ammessi(disp, "form_layout")
        sezioni = []
        for sezione in dati["form_layout"]:
            if not (isinstance(sezione, list) and len(sezione) == 2 and isinstance(sezione[1], list)):
                continue
            righe = [[c for c in r if isinstance(c, str) and c in ammessi] for r in sezione[1] if isinstance(r, list)]
            sezioni.append([str(sezione[0])[:80], [r for r in righe if r]])
        if sezioni:
            risultato["form_layout"] = sezioni
    if isinstance(dati.get("etichette"), dict):
        nomi = _ammessi(disp, "list_display") | _ammessi(disp, "form_layout")
        risultato["etichette"] = {k: str(e)[:80] for k, e in dati["etichette"].items() if k in nomi and str(e).strip()}
    return risultato


def errori(vista, dati):
    """Messaggi per una personalizzazione inviata dall'editor (vuoto se va bene)."""
    problemi = []
    disp = disponibili(vista)
    for attributo in LISTE:
        sconosciuti = [n for n in dati.get(attributo, []) if n.lstrip("-") not in _ammessi(disp, attributo)]
        if sconosciuti:
            problemi.append(f"{attributo}: campi sconosciuti {', '.join(map(str, sconosciuti))}.")
    if "list_display" in dati and not dati["list_display"]:
        problemi.append("La lista deve avere almeno una colonna.")
    if "per_page" in dati and not (isinstance(dati["per_page"], int) and 10 <= dati["per_page"] <= 500):
        problemi.append("Le righe per pagina vanno da 10 a 500.")
    if "form_layout" in dati:
        if originale(vista).form_class:
            problemi.append("Il form di questa vista non è personalizzabile.")
        else:
            nel_form = {c for s in dati["form_layout"] for r in s[1] for c in r}
            sconosciuti = nel_form - _ammessi(disp, "form_layout")
            if sconosciuti:
                problemi.append(f"Form: campi sconosciuti {', '.join(sorted(sconosciuti))}.")
            mancanti = [n for n in obbligatori(vista) if n not in nel_form]
            if mancanti:
                problemi.append(f"Il form deve contenere i campi obbligatori: {', '.join(mancanti)}.")
    return problemi
