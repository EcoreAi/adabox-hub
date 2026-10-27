"""Campi personalizzati: definizioni per modello e azienda, campi del form, conversione da/verso JSON."""
import datetime
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from .models import CampoPersonalizzato as C

VUOTO = "—"


def accetta(modello):
    return any(f.name == "proprieta" for f in modello._meta.get_fields())


def definizioni(modello, azienda=None):
    """Campi del modello validi per l'azienda (quelli per tutte più quelli dell'azienda), in ordine."""
    if not accetta(modello):
        return []
    azienda_id = getattr(azienda, "pk", None)       # request.azienda è lazy: può avvolgere None
    filtro = Q(azienda__isnull=True) | Q(azienda_id=azienda_id) if azienda_id is not None else Q(azienda__isnull=True)
    return list(C.objects.filter(filtro, modello=ContentType.objects.get_for_model(modello)).order_by("ordine", "pk"))


def nome_campo(d):
    return f"prop_{d.nome}"


def campo_form(d):
    comuni = {"label": d.label, "help_text": d.aiuto, "required": d.obbligatorio}
    if d.tipo == C.BOOLEANO:
        return forms.BooleanField(**{**comuni, "required": False})
    if d.tipo == C.INTERO:
        return forms.IntegerField(**comuni)
    if d.tipo == C.DECIMALE:
        return forms.DecimalField(**comuni)
    if d.tipo == C.DATA:
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), **comuni)
    if d.tipo == C.SCELTA:
        return forms.ChoiceField(choices=[("", "—")] + d.elenco_scelte(), **comuni)
    if d.tipo == C.UTENTE:
        return forms.ModelChoiceField(queryset=get_user_model().objects.filter(is_active=True), **comuni)
    return forms.CharField(max_length=500, **comuni)


def in_json(d, valore):
    if valore in (None, ""):
        return None
    if d.tipo == C.DATA:
        return valore.isoformat()
    if d.tipo == C.DECIMALE:
        return str(valore)
    if d.tipo == C.UTENTE:
        return valore.pk if hasattr(valore, "pk") else int(valore)
    return valore


def da_json(d, valore):
    if valore in (None, ""):
        return None
    try:
        if d.tipo == C.DATA:
            return datetime.date.fromisoformat(valore)
        if d.tipo == C.DECIMALE:
            return Decimal(str(valore))
        if d.tipo == C.UTENTE:
            return get_user_model().objects.filter(pk=valore).first()
    except (ValueError, TypeError, InvalidOperation):
        return None
    return valore


def testo(d, obj):
    """Valore leggibile della proprietà `d` per il record `obj` (lista e dettaglio)."""
    valore = da_json(d, (getattr(obj, "proprieta", None) or {}).get(d.nome))
    if valore is None:
        return VUOTO
    if d.tipo == C.BOOLEANO:
        return "Sì" if valore else "No"
    if d.tipo == C.SCELTA:
        return dict(d.elenco_scelte()).get(valore, valore)
    if d.tipo == C.DATA:
        return valore.strftime("%d/%m/%Y")
    if d.tipo == C.UTENTE:
        return valore.get_full_name() or valore.username
    return str(valore)


def form_con_proprieta(base, definizioni_campi):
    """Sottoclasse della ModelForm con i campi prop_<nome>; i valori si leggono e scrivono in instance.proprieta."""
    attributi = {nome_campo(d): campo_form(d) for d in definizioni_campi}

    def __init__(self, *args, **kwargs):
        base.__init__(self, *args, **kwargs)
        dati = getattr(self.instance, "proprieta", None) or {}
        for d in definizioni_campi:
            if d.nome in dati and nome_campo(d) not in self.initial:
                self.initial[nome_campo(d)] = da_json(d, dati[d.nome])

    def applica_proprieta(self, obj):
        valori = dict(obj.proprieta or {})                 # le chiavi di campi non definiti qui restano
        for d in definizioni_campi:
            valori[d.nome] = in_json(d, self.cleaned_data.get(nome_campo(d)))
        obj.proprieta = valori

    attributi.update({"__init__": __init__, "applica_proprieta": applica_proprieta,
                      "definizioni_proprieta": definizioni_campi, "__module__": base.__module__})
    return type(base)(f"{base.__name__}ConProprieta", (base,), attributi)
