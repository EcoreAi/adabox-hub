"""Strumenti di scrittura generati dalle ModelView: creare (anche con le righe del documento), modificare,
eliminare, premere un bottone, eseguire un'azione su più record, pianificare un'attività.

Ognuno ha un'anteprima, che valida con gli stessi form del browser e descrive la modifica senza salvare nulla, e
una funzione che salva, chiamata solo alla conferma dell'utente (ai.proposte). Il form, i permessi e
`save_model` della vista sono quelli dell'interfaccia: numeri di sequenza, azienda, chatter e tracciamento
funzionano come dal browser."""
import datetime
import hashlib
import json

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import router
from django.db.models import ProtectedError, RestrictedError
from django.db.models.deletion import Collector
from django.forms.models import model_to_dict
from django.http import HttpResponse
from django.utils import timezone

from . import richiesta
from .registro import ErroreStrumento, Strumento, registra
from .viste import VISTA, _ammesso, _decodifica, _url, campi_leggibili, oggetto, valore, vista_per

MAX_RIGHE = 100


# ---------- dati del form ----------

def _id(v):
    if isinstance(v, dict) and "id" in v:
        return v["id"]
    if isinstance(v, list):
        return [_id(x) for x in v]
    return v


def _campi_form(form, campi):
    """{campo: valore} del modello → dati del form; i campi personalizzati come prop_<nome>."""
    campi = dict(_decodifica(campi, "campi"))
    personalizzati = _decodifica(campi.pop("campi_personalizzati", None), "campi_personalizzati")
    dati = {}
    for chiave, v in [*campi.items(), *((f"prop_{k}", v) for k, v in personalizzati.items())]:
        nome = chiave if chiave in form.fields else f"prop_{chiave}" if f"prop_{chiave}" in form.fields else None
        if nome is None:
            raise ErroreStrumento(f"Il campo «{chiave}» non si può impostare: descrivi_vista indica i campi "
                                  "modificabili.")
        if isinstance(form.fields[nome], forms.FileField):
            raise ErroreStrumento(f"«{chiave}» è un file: i file non si caricano dalla chat.")
        dati[nome] = _id(v)
    return dati


def _iniziali(form, dati, prefisso=""):
    """I valori iniziali dei campi non indicati, come li manderebbe il browser (default del modello, oggi...)."""
    for nome, campo in form.fields.items():
        if nome in dati or isinstance(campo, forms.FileField):
            continue
        v = form.get_initial_for_field(campo, nome)
        if hasattr(v, "pk"):
            v = v.pk
        if v is None or v is False or v in ("", []) or hasattr(v, "all"):     # 0 resta: è un valore
            continue
        dati[nome] = v
    return {f"{prefisso}{k}": v for k, v in dati.items()}


def _errori(form):
    voci = []
    for nome, errori in form.errors.items():
        etichetta = "Generale" if nome == "__all__" else str(form.fields[nome].label or nome) if nome in form.fields \
            else nome
        voci.append(f"{etichetta}: {' '.join(str(e) for e in errori)}")
    return "; ".join(voci)


def _leggibile(campo, v):
    if v in (None, "", []):
        return "—"
    if isinstance(v, bool):
        return "sì" if v else "no"
    if hasattr(v, "all"):
        return ", ".join(str(o) for o in v.all()) or "—"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v) or "—"
    if isinstance(v, datetime.datetime):
        return v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, datetime.date):
        return v.strftime("%d/%m/%Y")
    scelte = dict(getattr(campo, "choices", None) or []) if not hasattr(v, "pk") else {}
    return str(scelte.get(v, scelte.get(str(v), v)))


def _etichetta(form, nome):
    return str(form.fields[nome].label or nome)


def _nome(obj):
    try:
        testo = str(obj)
    except Exception:
        return ""
    return "" if testo in ("", "None") or testo.endswith(" object (None)") else testo


def impronta_record(obj):
    """Impronta dei valori di un record: se cambia tra proposta e conferma, la conferma si rifiuta."""
    valori = {f.attname: str(getattr(obj, f.attname)) for f in obj._meta.concrete_fields}
    return {"hash": hashlib.sha256(json.dumps(valori, sort_keys=True).encode()).hexdigest()[:20]}


# ---------- crea ----------

def _dati_righe(vista, request, righe):
    righe = _decodifica(righe, "righe") if isinstance(righe, str) else (righe or [])
    if not isinstance(righe, list) or not all(isinstance(r, dict) for r in righe):
        raise ErroreStrumento("«righe» è una lista di oggetti {campo: valore}.")
    if righe and not vista.inlines:
        raise ErroreStrumento("Questa vista non ha righe.")
    if len(righe) > MAX_RIGHE:
        raise ErroreStrumento(f"Al massimo {MAX_RIGHE} righe.")
    dati = {}
    for i, (_, fs) in enumerate(vista.formsets(request, None)):
        elenco = righe if i == 0 else []
        prefisso = f"righe{i}"
        dati.update({f"{prefisso}-TOTAL_FORMS": str(len(elenco)), f"{prefisso}-INITIAL_FORMS": "0",
                     f"{prefisso}-MIN_NUM_FORMS": "0", f"{prefisso}-MAX_NUM_FORMS": "1000"})
        vuoto = fs.empty_form
        for j, riga in enumerate(elenco):
            sconosciuti = [k for k in riga if k not in vuoto.fields or k == "DELETE"]
            if sconosciuti:
                raise ErroreStrumento(f"Campi delle righe non validi: {', '.join(sconosciuti)}. Ammessi: "
                                      f"{', '.join(vista.inlines[0].fields)}.")
            dati.update(_iniziali(vuoto, {k: _id(v) for k, v in riga.items()}, f"{prefisso}-{j}-"))
    return dati


def _form_crea(contesto, vista, campi, righe):
    v = vista_per(contesto, vista)
    request = richiesta.per(contesto, "POST")
    if not v.has_add_permission(request):
        raise PermissionDenied
    form_class = v.get_form_class(request)
    vuoto = form_class()
    dati = _iniziali(vuoto, _campi_form(vuoto, campi))
    dati.update(_dati_righe(v, request, righe))
    form = form_class(data=dati)
    formsets = v.formsets(request, None, dati)
    if not form.is_valid():
        raise ErroreStrumento(f"Dati non validi: {_errori(form)}")
    for inline, fs in formsets:
        if not fs.is_valid():
            errori = [f"riga {i + 1}: {_errori(f)}" for i, f in enumerate(fs.forms) if f.errors]
            errori += [str(e) for e in fs.non_form_errors()]
            raise ErroreStrumento(f"{inline.titolo} non valide: {'; '.join(errori)}")
    return v, request, form, formsets


def anteprima_crea(contesto, vista, campi=None, righe=None):
    v, _, form, formsets = _form_crea(contesto, vista, campi, righe)
    nome = _nome(form.instance)
    dettagli = [{"campo": _etichetta(form, n), "dopo": _leggibile(form.fields[n], form.cleaned_data.get(n))}
                for n in form.changed_data]
    for inline, fs in formsets:
        for i, f in enumerate(x for x in fs.forms if x.has_changed()):
            descrizione = ", ".join(f"{_etichetta(f, n)} {_leggibile(f.fields[n], f.cleaned_data.get(n))}"
                                    for n in f.changed_data)
            dettagli.append({"campo": f"{inline.titolo} {i + 1}", "dopo": descrizione})
    return {"titolo": f"Crea {v.verbose_name}" + (f" «{nome}»" if nome else ""), "dettagli": dettagli}


def crea_record(contesto, vista, campi=None, righe=None):
    from django.db import transaction
    v, request, form, formsets = _form_crea(contesto, vista, campi, righe)
    with transaction.atomic():
        obj = form.save(commit=False)
        v.save_model(request, obj, form, change=False)
        for _, fs in formsets:
            fs.instance = obj
            fs.save()
        if formsets:
            v.dopo_righe(request, obj)
    return {"esito": f"Creato: {v.verbose_name} «{obj}».", "url": _url(v, obj), "record": obj}


# ---------- modifica ----------

def _form_modifica(contesto, vista, id, campi):
    v = vista_per(contesto, vista)
    request = richiesta.per(contesto, "POST")
    obj = oggetto(v, request, id)
    if not v.has_change_permission(request, obj):
        raise PermissionDenied
    form_class = v.get_form_class(request)
    vuoto = form_class(instance=obj)
    cambi = _campi_form(vuoto, campi)
    if not cambi:
        raise ErroreStrumento("Indica almeno un campo da modificare.")
    attuali = model_to_dict(obj, fields=[n for n in vuoto.fields if not n.startswith("prop_")])
    attuali = {k: [o.pk for o in x] if isinstance(x, list) else x for k, x in attuali.items()}
    attuali.update({f"prop_{k}": x for k, x in (getattr(obj, "proprieta", None) or {}).items()})
    campi_modello = {f.name: f for f in campi_leggibili(v)}
    prima = {n: _leggibile(vuoto.fields[n], vuoto.get_initial_for_field(vuoto.fields[n], n)) for n in cambi}
    impronta = {n: valore(obj, campi_modello[n]) if n in campi_modello else attuali.get(n) for n in cambi}
    impronta = json.loads(json.dumps(impronta, default=str))
    form = form_class(data={**attuali, **cambi}, instance=obj)
    if not form.is_valid():
        raise ErroreStrumento(f"Dati non validi: {_errori(form)}")
    return v, request, obj, form, prima, impronta


def anteprima_modifica(contesto, vista, id, campi=None):
    v, _, obj, form, prima, impronta = _form_modifica(contesto, vista, id, campi)
    dettagli = [{"campo": _etichetta(form, n), "prima": prima[n],
                 "dopo": _leggibile(form.fields[n], form.cleaned_data.get(n))} for n in prima]
    dettagli = [d for d in dettagli if d["prima"] != d["dopo"]]
    if not dettagli:
        raise ErroreStrumento("Nessuna modifica: i campi hanno già questi valori.")
    return {"titolo": f"Modifica {v.verbose_name} «{obj}»", "dettagli": dettagli, "impronta": impronta,
            "url": _url(v, obj)}


def modifica_record(contesto, vista, id, campi=None):
    v, request, obj, form, _, _ = _form_modifica(contesto, vista, id, campi)
    obj = form.save(commit=False)
    v.save_model(request, obj, form, change=True)
    return {"esito": f"Modificato: {v.verbose_name} «{obj}».", "url": _url(v, obj), "record": obj}


# ---------- elimina ----------

def _da_eliminare(contesto, vista, id):
    v = vista_per(contesto, vista)
    request = richiesta.per(contesto, "POST")
    obj = oggetto(v, request, id)
    if not v.has_delete_permission(request, obj):
        raise PermissionDenied
    return v, obj


def anteprima_elimina(contesto, vista, id):
    v, obj = _da_eliminare(contesto, vista, id)
    raccolta = Collector(using=router.db_for_write(type(obj)))
    try:
        raccolta.collect([obj])
    except (ProtectedError, RestrictedError):
        raise ErroreStrumento(f"«{obj}» non si può eliminare: altri dati vi fanno riferimento.")
    altri = {}
    for modello, oggetti in raccolta.data.items():
        n = len([o for o in oggetti if o is not obj and not (type(o) is type(obj) and o.pk == obj.pk)])
        if n:
            altri[str(modello._meta.verbose_name_plural)] = altri.get(str(modello._meta.verbose_name_plural), 0) + n
    for qs in raccolta.fast_deletes:
        if n := qs.count():
            nome = str(qs.model._meta.verbose_name_plural)
            altri[nome] = altri.get(nome, 0) + n
    riepilogo = f"Eliminazione definitiva di {v.verbose_name} «{obj}»: non si può annullare."
    if altri:
        riepilogo += " Saranno eliminati anche: " + ", ".join(f"{n} {nome}" for nome, n in altri.items()) + "."
    return {"titolo": f"Elimina {v.verbose_name} «{obj}»", "rischio": "irreversibile", "riepilogo": riepilogo,
            "impronta": impronta_record(obj), "url": _url(v, obj)}


def elimina_record(contesto, vista, id):
    v, obj = _da_eliminare(contesto, vista, id)
    nome = str(obj)
    try:
        obj.delete()
    except (ProtectedError, RestrictedError):
        raise ErroreStrumento(f"«{nome}» non si può eliminare: altri dati vi fanno riferimento.")
    return {"esito": f"Eliminato: {v.verbose_name} «{nome}».", "url": _url_lista(v)}


def _url_lista(vista):
    try:
        return vista.url("lista")
    except Exception:
        return ""


# ---------- bottoni e azioni ----------

def _bottone(contesto, vista, id, bottone):
    v = vista_per(contesto, vista)
    request = richiesta.per(contesto, "POST")
    obj = oggetto(v, request, id)
    disponibili = {n: e for n, e in v.get_buttons(request, obj) if _ammesso(getattr(v, n))}
    if bottone not in disponibili:
        elenco = ", ".join(disponibili) or "nessuno"
        raise ErroreStrumento(f"Il bottone «{bottone}» non è disponibile ora per «{obj}». Disponibili: {elenco}.")
    return v, request, obj, getattr(v, bottone), str(disponibili[bottone])


def anteprima_bottone(contesto, vista, id, bottone):
    v, _, obj, metodo, etichetta = _bottone(contesto, vista, id, bottone)
    rischio = getattr(metodo, "rischio", "scrittura")
    a = {"titolo": f"{etichetta}: {v.verbose_name} «{obj}»", "rischio": rischio, "impronta": impronta_record(obj),
         "url": _url(v, obj)}
    if rischio == "irreversibile":
        a["riepilogo"] = f"«{etichetta}» su {v.verbose_name} «{obj}» non si può annullare."
    return a


def _esito(risultato, request, url):
    testi = [str(risultato)] if isinstance(risultato, str) and risultato else []
    if isinstance(risultato, HttpResponse):
        if 300 <= risultato.status_code < 400:
            url = risultato["Location"]
        else:
            testi.append("Fatto: il risultato è un file, aprilo dal record.")
    testi += richiesta.messaggi(request)
    return " ".join(testi) or "Fatto.", url


def esegui_bottone(contesto, vista, id, bottone):
    v, request, obj, metodo, _ = _bottone(contesto, vista, id, bottone)
    esito, url = _esito(metodo(request, obj), request, _url(v, obj))
    obj.refresh_from_db()
    return {"esito": esito, "url": url, "record": obj}


def _azione(contesto, vista, azione, ids):
    v = vista_per(contesto, vista)
    request = richiesta.per(contesto, "POST")
    disponibili = {n: e for n, e in v.get_actions(request) if _ammesso(getattr(v, n))}
    if azione not in disponibili:
        raise ErroreStrumento(f"Azione «{azione}» non disponibile. Disponibili: {', '.join(disponibili) or 'nessuna'}.")
    try:
        ids = sorted({int(i) for i in _id(ids or [])})
    except (TypeError, ValueError):
        raise ErroreStrumento("«ids» è una lista di id interi.")
    if not ids or len(ids) > MAX_RIGHE:
        raise ErroreStrumento(f"Indica da 1 a {MAX_RIGHE} record.")
    qs = v.get_queryset(request).filter(pk__in=ids)
    trovati = list(qs)
    if len(trovati) != len(ids):
        mancanti = sorted(set(ids) - {o.pk for o in trovati})
        raise ErroreStrumento(f"Record non trovati o non visibili: {', '.join(map(str, mancanti))}.")
    return v, request, qs, trovati, getattr(v, azione), str(disponibili[azione])


def anteprima_azione(contesto, vista, azione, ids):
    v, _, _, trovati, metodo, etichetta = _azione(contesto, vista, azione, ids)
    rischio = getattr(metodo, "rischio", "scrittura")
    a = {"titolo": f"{etichetta}: {len(trovati)} {v.verbose_name_plural if len(trovati) != 1 else v.verbose_name}",
         "rischio": rischio, "dettagli": [{"campo": "Record", "dopo": str(o)} for o in trovati[:20]],
         "impronta": {"hash": "".join(impronta_record(o)["hash"] for o in sorted(trovati, key=lambda o: o.pk))[:200]}}
    if len(trovati) > 20:
        a["dettagli"].append({"campo": "Record", "dopo": f"… e altri {len(trovati) - 20}"})
    if rischio == "irreversibile":
        a["riepilogo"] = f"«{etichetta}» su {len(trovati)} record non si può annullare."
    return a


def esegui_azione(contesto, vista, azione, ids):
    v, request, qs, _, metodo, _ = _azione(contesto, vista, azione, ids)
    esito, url = _esito(metodo(request, qs), request, _url_lista(v))
    return {"esito": esito, "url": url}


# ---------- attività pianificate sul record ----------

def _attivita(contesto, vista, id, tipo, scadenza="", assegnatario=""):
    from core.models import TipoAttivita
    v = vista_per(contesto, vista)
    request = richiesta.per(contesto, "POST")
    obj = oggetto(v, request, id)
    if not v.has_change_permission(request, obj):
        raise PermissionDenied
    t = TipoAttivita.objects.filter(nome__iexact=(tipo or "").strip()).first()
    if t is None:
        nomi = ", ".join(TipoAttivita.objects.values_list("nome", flat=True))
        raise ErroreStrumento(f"Tipo di attività «{tipo}» inesistente. Tipi: {nomi or 'nessuno'}.")
    utenti = get_user_model().objects.filter(is_active=True)
    persona = utenti.filter(username=assegnatario).first() if assegnatario else contesto.utente
    if persona is None:
        raise ErroreStrumento(f"Utente «{assegnatario}» inesistente o non attivo (serve lo username).")
    try:
        data = datetime.date.fromisoformat(scadenza) if scadenza else \
            timezone.localdate() + datetime.timedelta(days=t.giorni)
    except (TypeError, ValueError):
        raise ErroreStrumento("«scadenza» è una data AAAA-MM-GG.")
    return v, obj, t, persona, data


def anteprima_attivita(contesto, vista, id, tipo, scadenza="", riepilogo="", nota="", assegnatario=""):
    v, obj, t, persona, data = _attivita(contesto, vista, id, tipo, scadenza, assegnatario)
    dettagli = [{"campo": "Tipo", "dopo": str(t)}, {"campo": "Scadenza", "dopo": data.strftime("%d/%m/%Y")},
                {"campo": "Assegnata a", "dopo": persona.get_full_name() or persona.username}]
    dettagli += [{"campo": c, "dopo": x} for c, x in (("Riepilogo", riepilogo), ("Nota", nota)) if x]
    return {"titolo": f"Pianifica «{t}» su {v.verbose_name} «{obj}»", "dettagli": dettagli, "url": _url(v, obj)}


def pianifica_attivita(contesto, vista, id, tipo, scadenza="", riepilogo="", nota="", assegnatario=""):
    from core import attivita
    v, obj, t, persona, data = _attivita(contesto, vista, id, tipo, scadenza, assegnatario)
    attivita.pianifica(obj, t, persona, data, (riepilogo or "")[:200], nota or "", creato_da=contesto.utente)
    return {"esito": f"Attività «{t}» pianificata per il {data:%d/%m/%Y} su «{obj}».", "url": _url(v, obj),
            "record": obj}


# ---------- registrazione ----------

ID = {"type": "integer", "description": "id del record"}
CAMPI = {"type": "object", "additionalProperties": True,
         "description": "{campo: valore}; relazioni con l'id (o lista di id), scelte con il codice, date AAAA-MM-GG; "
                        "campi personalizzati in campi_personalizzati: {nome: valore}"}
DOPO = " Non esegue nulla: prepara una proposta che l'utente conferma con un bottone."

registra(Strumento(
    "crea_record", "Crea un record in una vista, con le righe del documento se la vista le ha (es. righe di un "
                   "preventivo). I campi non indicati prendono i valori predefiniti." + DOPO,
    {"type": "object", "properties": {
        "vista": VISTA, "campi": CAMPI,
        "righe": {"type": "array", "items": {"type": "object", "additionalProperties": True},
                  "description": "righe del documento: [{campo: valore}], campi come in descrivi_vista → righe"}},
     "required": ["vista", "campi"]}, crea_record, rischio="scrittura", concorrente=False, anteprima=anteprima_crea))
registra(Strumento(
    "modifica_record", "Modifica i campi indicati di un record (gli altri restano come sono)." + DOPO,
    {"type": "object", "properties": {"vista": VISTA, "id": ID, "campi": CAMPI}, "required": ["vista", "id", "campi"]},
    modifica_record, rischio="scrittura", concorrente=False, anteprima=anteprima_modifica))
registra(Strumento(
    "elimina_record", "Elimina definitivamente un record." + DOPO,
    {"type": "object", "properties": {"vista": VISTA, "id": ID}, "required": ["vista", "id"]},
    elimina_record, rischio="irreversibile", concorrente=False, anteprima=anteprima_elimina))
registra(Strumento(
    "esegui_bottone", "Preme un bottone del record (es. conferma, invia, segna fatta): i bottoni disponibili sono in "
                      "leggi_record." + DOPO,
    {"type": "object", "properties": {"vista": VISTA, "id": ID, "bottone": {"type": "string",
                                                                           "description": "nome del bottone"}},
     "required": ["vista", "id", "bottone"]}, esegui_bottone, rischio="scrittura", concorrente=False,
    anteprima=anteprima_bottone))
registra(Strumento(
    "esegui_azione", "Esegue un'azione su più record insieme (azioni_su_piu_record di descrivi_vista)." + DOPO,
    {"type": "object", "properties": {"vista": VISTA, "azione": {"type": "string"},
                                      "ids": {"type": "array", "items": {"type": "integer"}}},
     "required": ["vista", "azione", "ids"]}, esegui_azione, rischio="scrittura", concorrente=False,
    anteprima=anteprima_azione))
registra(Strumento(
    "pianifica_attivita", "Pianifica un'attività (chiamata, email, riunione, da fare...) su un record, con scadenza e "
                          "assegnatario (default: l'utente)." + DOPO,
    {"type": "object", "properties": {
        "vista": VISTA, "id": ID, "tipo": {"type": "string", "description": "tipo di attività, es. Chiamata"},
        "scadenza": {"type": "string", "description": "AAAA-MM-GG (default: secondo il tipo)"},
        "riepilogo": {"type": "string"}, "nota": {"type": "string"},
        "assegnatario": {"type": "string", "description": "username (default: l'utente)"}},
     "required": ["vista", "id", "tipo"]}, pianifica_attivita, rischio="scrittura", concorrente=False,
    anteprima=anteprima_attivita))
