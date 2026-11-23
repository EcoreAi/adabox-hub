"""Un modulo con una relazione verso il modello di un altro modulo deve dichiararlo tra le dipendenze (anche indirette):
senza, su un'istanza che non ha quel modulo l'avvio cade (es. discuss e flotta verso contatti.Contatto)."""
from django.apps import apps
from django.conf import settings

from core.registry import modules


def _chiusura(slug, info, visti=None):
    visti = set() if visti is None else visti
    for d in modules.dipendenze(slug, info):
        if d not in visti:
            visti.add(d)
            _chiusura(d, info, visti)
    return visti


def test_le_relazioni_verso_altri_moduli_sono_dipendenze_dichiarate():
    info = modules.scopri()
    addons = set(settings.ADDONS_ATTIVI)
    mancanti = []
    for slug in sorted(addons):
        if slug not in info or info[slug].manifest is None:
            continue
        richieste = _chiusura(slug, info)
        for modello in apps.get_app_config(slug).get_models():
            for campo in modello._meta.get_fields():
                if not campo.is_relation or campo.auto_created or campo.related_model is None:
                    continue
                verso = campo.related_model._meta.app_label
                if verso in addons and verso != slug and verso not in richieste:
                    mancanti.append(f"{modello._meta.label}.{campo.name} -> {campo.related_model._meta.label}")
    assert not mancanti, "relazioni verso moduli non dichiarati in depends: " + "; ".join(mancanti)
