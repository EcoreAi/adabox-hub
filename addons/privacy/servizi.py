"""Consensi, esportazione dei dati di un contatto, anonimizzazione e conservazione.

Anonimizzare non cancella i documenti: i record legati al contatto con PROTECT (fatture, ordini, consegne, contratti,
mandati) vanno conservati per legge, quindi se ce ne sono restano i dati che servono a loro (ragione sociale, partita
IVA, codice fiscale, indirizzo di fatturazione, codice SDI e PEC) e si toglie tutto il resto. Senza documenti da
conservare l'anonimizzazione è completa."""
import datetime
import json
from decimal import Decimal

from django.apps import apps
from django.db import models, transaction
from django.forms.models import model_to_dict
from django.utils import timezone

from core import chatter

from .models import Anonimizzazione, Consenso, Finalita, RegolaConservazione

DATI_FISCALI = {"nome", "partita_iva", "codice_fiscale", "indirizzo", "cap", "citta", "provincia", "nazione", "codice_sdi",
                "pec", "pubblica_amministrazione", "tipo", "codice", "azienda", "cliente", "fornitore"}
PERSONALI_COLLEGATI = ("email", "telefono", "cellulare", "nome_contatto", "email_cliente", "nome_cliente")
SEGNAPOSTO = "Contatto anonimizzato"


# ---------- consensi

def stato_consensi(contatto):
    """[(finalità, ultima registrazione o None)] per le finalità attive."""
    ultimi = {}
    for c in Consenso.objects.filter(contatto=contatto).select_related("registrato_da"):
        ultimi.setdefault(c.finalita_id, c)
    return [(f, ultimi.get(f.pk)) for f in Finalita.objects.filter(attiva=True)]


def registra(contatto, finalita, dato, fonte="persona", utente=None, note=""):
    c = Consenso.objects.create(azienda=contatto.azienda, contatto=contatto, finalita=finalita, dato=dato, fonte=fonte,
                                note=note[:250], registrato_da=utente)
    chatter.scrivi(contatto, utente, f"Consenso «{finalita}» {'dato' if dato else 'revocato'} ({c.get_fonte_display().lower()}).",
                   tipo="sistema")
    return c


def ha_consenso(contatto, finalita):
    ultimo = Consenso.objects.filter(contatto=contatto, finalita=finalita).first()
    return bool(ultimo and ultimo.dato)


# ---------- esportazione

def _valore(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, models.Model):
        return str(v)
    if hasattr(v, "name") and hasattr(v, "url"):           # file
        return v.name or ""
    if isinstance(v, (list, tuple)):
        return [_valore(x) for x in v]
    return v


def _record(obj):
    campi = [f.name for f in obj._meta.concrete_fields if not f.name.endswith(("_cifrato", "_hash"))]
    dati = {k: _valore(v) for k, v in model_to_dict(obj, fields=campi).items()}
    return {"tipo": str(obj._meta.verbose_name), "id": obj.pk, "descrizione": str(obj), "dati": dati}


def esporta(contatto):
    """Tutti i dati del contatto, in ogni app: anagrafica, indirizzi, consensi, i record che lo citano e i messaggi."""
    collegati = {}
    for rel in contatto._meta.related_objects:
        if rel.related_model is Consenso:
            continue
        accessore = rel.get_accessor_name()
        try:
            righe = list(getattr(contatto, accessore).all()[:500]) if rel.one_to_many or rel.many_to_many else []
        except Exception:                                  # noqa: BLE001 - relazione senza manager leggibile
            continue
        if righe:
            collegati[str(rel.related_model._meta.verbose_name_plural)] = [_record(r) for r in righe]
    return {
        "esportato_il": timezone.now().isoformat(), "contatto": _record(contatto),
        "consensi": [{"finalita": c.finalita.nome, "dato": c.dato, "il": c.il.isoformat(), "come": c.get_fonte_display(),
                      "note": c.note} for c in Consenso.objects.filter(contatto=contatto).select_related("finalita")],
        "collegati": collegati,
        "messaggi": [{"il": m.creato.isoformat(), "tipo": m.get_tipo_display(), "testo": m.corpo,
                      "modifiche": m.modifiche} for m in chatter.messaggi_di(contatto)[:500]],
    }


def esporta_json(contatto):
    return json.dumps(esporta(contatto), ensure_ascii=False, indent=2, default=str)


# ---------- anonimizzazione

def documenti_da_conservare(contatto):
    """{nome dei record: quanti} legati al contatto con PROTECT: documenti che la legge chiede di conservare."""
    trovati = {}
    for rel in contatto._meta.related_objects:
        if rel.one_to_many and getattr(rel, "on_delete", None) is models.PROTECT:
            n = rel.related_model._default_manager.filter(**{rel.field.name: contatto}).count()
            if n:
                trovati[str(rel.related_model._meta.verbose_name_plural)] = n
    return trovati


def _pulisci_collegati(contatto, tolti):
    """Nei record non fiscali che citano il contatto si tolgono email, telefoni e nomi copiati (opportunità, ticket…)."""
    for rel in contatto._meta.related_objects:
        modello = rel.related_model
        if rel.many_to_many:
            # Sulla tabella di collegamento e non con l'accessor: con related_name="+" l'accessor non esiste.
            n, _ = rel.through._default_manager.filter(**{rel.field.m2m_reverse_field_name(): contatto}).delete()
            if n:
                tolti.append(f"collegamenti con {modello._meta.verbose_name_plural}")
            continue
        if not rel.one_to_many or getattr(rel, "on_delete", None) is models.PROTECT or modello is Consenso:
            continue
        campi = [f.name for f in modello._meta.concrete_fields if f.name in PERSONALI_COLLEGATI]
        if campi:
            n = modello._default_manager.filter(**{rel.field.name: contatto}).update(**{c: "" for c in campi})
            if n:
                tolti.append(f"{', '.join(campi)} in {n} {modello._meta.verbose_name_plural}")


@transaction.atomic
def anonimizza(contatto, utente=None):
    """Toglie i dati personali del contatto (vedi il docstring del modulo). Irreversibile; restituisce l'Anonimizzazione."""
    if hasattr(contatto, "anonimizzazione"):
        raise ValueError("Questo contatto è già stato anonimizzato.")
    documenti = documenti_da_conservare(contatto)
    parziale = bool(documenti)
    tolti = []
    for f in contatto._meta.concrete_fields:
        if f.primary_key or f.name in ("azienda",) or (parziale and f.name in DATI_FISCALI):
            continue
        if isinstance(f, (models.CharField, models.TextField, models.EmailField, models.URLField)) and getattr(contatto, f.name):
            if f.name == "nome":
                setattr(contatto, f.name, f"{SEGNAPOSTO} {contatto.pk}")
            elif f.name == "nazione":
                continue
            else:
                setattr(contatto, f.name, "")
            tolti.append(str(f.verbose_name))
        elif f.name in ("responsabile", "societa", "fido") and getattr(contatto, f.name) is not None:
            setattr(contatto, f.name, None)
            tolti.append(str(f.verbose_name))
    if getattr(contatto, "proprieta", None):
        contatto.proprieta = {}
        tolti.append("campi personalizzati")
    contatto.attivo = False
    contatto.save()
    contatto.categorie.clear()
    indirizzi = contatto.indirizzi.all()
    if parziale:
        indirizzi = indirizzi.exclude(tipo="fatturazione")
    n, _ = indirizzi.delete()
    if n:
        tolti.append(f"{n} indirizzi")
    _pulisci_collegati(contatto, tolti)
    if apps.is_installed("portale"):
        from portale.models import AccessoPortale
        for a in AccessoPortale.objects.filter(contatto=contatto).select_related("utente"):
            utente_portale = a.utente
            utente_portale.is_active, utente_portale.email, utente_portale.first_name, utente_portale.last_name = False, "", "", ""
            utente_portale.save()
            a.delete()
            tolti.append("accesso al portale")
    from core import allegati
    from core.models import Messaggio
    for allegato in allegati.di(contatto):
        allegato.file.delete(save=False)
        allegato.delete()
    messaggi = chatter.messaggi_di(contatto).exclude(tipo=Messaggio.SISTEMA)
    if messaggi.update(corpo="[anonimizzato]", autore_email=""):
        tolti.append("testo dei messaggi")
    Messaggio.objects.filter(pk__in=chatter.messaggi_di(contatto).filter(tipo=Messaggio.TRACCIAMENTO).values("pk")).update(modifiche=[])
    for finalita, ultimo in stato_consensi(contatto):
        if ultimo is not None and ultimo.dato:
            Consenso.objects.create(azienda=contatto.azienda, contatto=contatto, finalita=finalita, dato=False,
                                    fonte="persona", note="revocato con l'anonimizzazione", registrato_da=utente)
    from core.generici import ct_di
    from core.models import RegistroModifica
    RegistroModifica.objects.filter(content_type=ct_di(contatto), object_id=contatto.pk).update(   # i valori vecchi
        modifiche=[], oggetto=str(contatto)[:200])
    tolti.append("valori precedenti nel registro delle modifiche")
    esito = Anonimizzazione.objects.create(contatto=contatto, da=utente, parziale=parziale, dettagli=tolti)
    chatter.scrivi(contatto, utente, "Contatto anonimizzato" + (
        f": restano i dati che servono a {', '.join(documenti)} da conservare per legge." if parziale else "."), tipo="sistema")
    return esito


# ---------- conservazione

def applica_conservazione():
    """Lavoro pianificato: per ogni regola attiva cancella i record più vecchi dei giorni scelti."""
    from . import conservazione
    tipi, totale = conservazione.tipi(), 0
    for regola in RegolaConservazione.objects.filter(attiva=True, giorni__gt=0):
        voce = tipi.get(regola.chiave)
        if voce is None:
            continue
        modello = apps.get_model(voce["modello"])
        limite = timezone.now() - datetime.timedelta(days=regola.giorni)
        campo = modello._meta.get_field(voce["campo_data"])
        valore = limite.date() if isinstance(campo, models.DateField) and not isinstance(campo, models.DateTimeField) else limite
        qs = modello._default_manager.filter(**{f"{voce['campo_data']}__lt": valore})
        if voce["filtro"]:
            qs = voce["filtro"](qs)
        n, _ = qs.delete()
        regola.ultima_esecuzione, regola.cancellati = timezone.now(), n
        regola.save(update_fields=["ultima_esecuzione", "cancellati"])
        totale += n
    return totale
