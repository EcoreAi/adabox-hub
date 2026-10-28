"""Personalizzazioni di Studio: applicazione alle viste, salvataggio con storico, esportazione e importazione."""
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from core.models import CampoPersonalizzato
from core.viste import registry

from . import campi
from .models import Personalizzazione

MAX_VERSIONI = 20
FORMATO = "adabox-studio"


def per_vista(vista, request):
    """Funzione registrata nel kernel: gli attributi da sovrascrivere per questa vista."""
    riga = Personalizzazione.objects.filter(modulo=vista.modulo, vista=vista.slug).only("dati").first()
    return campi.pulisci(vista, riga.dati) if riga and riga.dati else {}


def trova(modulo, slug):
    return next((v for v in registry.viste_di(modulo) if v.slug == slug), None)


def tutte():
    """[(modulo, [viste])] delle viste registrate, in ordine."""
    from core.viste.registry import _viste
    return [(m, sorted(viste, key=lambda v: str(v.verbose_name_plural))) for m, viste in sorted(_viste.items())]


def solo_differenze(vista, dati):
    """Tiene solo gli attributi diversi da quelli del modulo: gli altri seguono gli aggiornamenti."""
    originali = campi.valori_originali(vista)
    return {k: v for k, v in dati.items() if originali.get(k) != v}


@transaction.atomic
def salva(vista, dati, utente=None):
    riga, _ = Personalizzazione.objects.select_for_update().get_or_create(modulo=vista.modulo, vista=vista.slug)
    nuovi = solo_differenze(vista, dati)
    if nuovi == riga.dati:
        return riga
    if riga.dati or riga.storico:
        riga.storico = [{"dati": riga.dati, "utente": getattr(riga.modificato_da, "username", ""),
                         "quando": riga.modificato_il.isoformat() if riga.modificato_il else ""},
                        *riga.storico][:MAX_VERSIONI]
    riga.dati, riga.modificato_da = nuovi, utente
    riga.save()
    return riga


def ripristina(vista, indice=None, utente=None):
    """Torna alla versione `indice` dello storico, o all'originale del modulo se None."""
    riga = Personalizzazione.objects.filter(modulo=vista.modulo, vista=vista.slug).first()
    if riga is None:
        return None
    dati = {} if indice is None else riga.storico[indice]["dati"]
    return salva(vista, {**campi.valori_originali(vista), **dati}, utente)


def esporta():
    campi_globali = CampoPersonalizzato.objects.filter(azienda__isnull=True).select_related("modello")
    return {
        "formato": FORMATO, "versione": 1, "esportato_il": timezone.now().isoformat(),
        "personalizzazioni": [{"modulo": p.modulo, "vista": p.vista, "dati": p.dati}
                              for p in Personalizzazione.objects.exclude(dati={})],
        "campi": [{"modello": f"{c.modello.app_label}.{c.modello.model}", "nome": c.nome, "label": c.label,
                   "tipo": c.tipo, "scelte": c.scelte, "aiuto": c.aiuto, "obbligatorio": c.obbligatorio,
                   "in_lista": c.in_lista, "filtrabile": c.filtrabile, "ordine": c.ordine} for c in campi_globali],
    }


@transaction.atomic
def importa(contenuto, utente=None):
    """(importate, saltate): prima i campi personalizzati, poi le viste che esistono in questa istanza."""
    if not isinstance(contenuto, dict) or contenuto.get("formato") != FORMATO:
        raise ValueError("Non è un file di personalizzazioni di Studio.")
    importate, saltate = [], []
    for c in contenuto.get("campi", []):
        app_label, _, model = str(c.get("modello", "")).partition(".")
        tipo = ContentType.objects.filter(app_label=app_label, model=model).first()
        if tipo is None or tipo.model_class() is None:
            saltate.append(f"campo {c.get('nome')} di {c.get('modello')}")
            continue
        valori = {k: c[k] for k in ("label", "tipo", "scelte", "aiuto", "obbligatorio", "in_lista", "filtrabile",
                                    "ordine") if k in c}
        campo = CampoPersonalizzato.objects.filter(modello=tipo, nome=c["nome"], azienda__isnull=True).first()
        campo = campo or CampoPersonalizzato(modello=tipo, nome=c["nome"])
        for k, v in valori.items():
            setattr(campo, k, v)
        campo.full_clean()
        campo.save()
        importate.append(f"campo {c['nome']}")
    for p in contenuto.get("personalizzazioni", []):
        vista = trova(p.get("modulo"), p.get("vista"))
        if vista is None:
            saltate.append(f"vista {p.get('modulo')}:{p.get('vista')}")
            continue
        salva(vista, {**campi.valori_originali(vista), **campi.pulisci(vista, p.get("dati") or {})}, utente)
        importate.append(f"vista {p['modulo']}:{p['vista']}")
    return importate, saltate
