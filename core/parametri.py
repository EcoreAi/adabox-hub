"""Parametri dei moduli: dichiarati nel manifest (`settings`), letti con precedenza azienda → globale → default."""
import datetime
from decimal import Decimal

from django import forms

from .models import Parametro
from .registry import modules


def definizioni():
    """{"<modulo>.<chiave>": voce del manifest con "modulo"} per i moduli installati."""
    return {f"{slug}.{v['chiave']}": {**v, "modulo": slug}
            for slug, m in modules.manifests_attivi().items() for v in m.settings}


def _da_json(tipo, valore):
    if valore is None:
        return None
    if tipo == "decimale":
        return Decimal(str(valore))
    if tipo == "data":
        return datetime.date.fromisoformat(valore) if isinstance(valore, str) else valore
    if tipo == "intero":
        return int(valore)
    if tipo == "booleano":
        return bool(valore)
    return valore


def _a_json(tipo, valore):
    if valore is None:
        return None
    if tipo == "decimale":
        return str(valore)
    if tipo == "data":
        return valore.isoformat()
    return valore


def leggi(chiave, azienda=None):
    """Valore del parametro: per l'azienda (se la voce è per_azienda), poi globale, poi il default del manifest.
    KeyError se nessun modulo installato dichiara la chiave."""
    voce = definizioni()[chiave]
    candidati = Parametro.objects.filter(chiave=chiave)
    if voce.get("per_azienda") and azienda is not None:
        if (p := candidati.filter(azienda=azienda).first()) is not None:
            return _da_json(voce["tipo"], p.valore)
    if (p := candidati.filter(azienda__isnull=True).first()) is not None:
        return _da_json(voce["tipo"], p.valore)
    return _da_json(voce["tipo"], voce.get("default"))


def scrivi(chiave, valore, azienda=None):
    """Salva per l'azienda (solo se la voce è per_azienda) o globale."""
    voce = definizioni()[chiave]
    azienda = azienda if voce.get("per_azienda") else None
    Parametro.objects.update_or_create(chiave=chiave, azienda=azienda,
                                       defaults={"valore": _a_json(voce["tipo"], valore)})


def _campo(voce):
    comuni = {"label": voce["label"], "help_text": voce.get("help", "")}
    tipo = voce["tipo"]
    if tipo == "booleano":
        return forms.BooleanField(required=False, **comuni)
    if tipo == "intero":
        return forms.IntegerField(**comuni)
    if tipo == "decimale":
        return forms.DecimalField(**comuni)
    if tipo == "data":
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), **comuni)
    if tipo == "scelta":
        return forms.ChoiceField(choices=[tuple(c) for c in voce["scelte"]], **comuni)
    return forms.CharField(required=False, **comuni)


class ImpostazioniForm(forms.Form):
    """Form delle impostazioni di un modulo; i valori iniziali sono quelli in vigore per l'azienda."""

    def __init__(self, modulo, azienda, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.modulo, self.azienda = modulo, azienda
        self.voci = {k: v for k, v in definizioni().items() if v["modulo"] == modulo}
        for chiave, voce in self.voci.items():
            nome = voce["chiave"]
            self.fields[nome] = _campo(voce)
            self.fields[nome].per_azienda = bool(voce.get("per_azienda"))
            self.initial[nome] = leggi(chiave, azienda)

    def salva(self):
        for chiave, voce in self.voci.items():
            scrivi(chiave, self.cleaned_data[voce["chiave"]], self.azienda)
