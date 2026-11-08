"""Strumenti di lettura generati dalle ModelView del kernel: quali viste ci sono, com'è fatta una vista, ricerca,
dettaglio e aggregazioni. Sono strumenti generici con la vista come argomento ("vendite.ordini"): il codice
valida vista, campi, filtri e permessi a ogni chiamata, sempre con l'utente e l'azienda di chi chiede.
Il motore (filtri, percorsi dei campi, aggregazioni) è quello del kernel, core.viste.interroga: qui restano gli
strumenti e la forma dei risultati per il modello."""
import datetime
from decimal import Decimal

from django.db import models
from django.http import Http404
from django.utils import timezone

from core.viste import registry
from core.viste.interroga import (  # noqa: F401  (anche riesportati per gli altri strumenti e i test)
    AGGREGATI, ESCLUSE, GRUPPI_MASSIMI, OPERATORI, SENSIBILE, SOLO_DATA, TRONCATURE, _campo, _decodifica,
    _etichette_gruppi, _misura, _numero, _percorso, _sensibile, aggrega, campi_leggibili, filtra, id_vista,
    viste_accessibili)

from . import richiesta
from .registro import ErroreStrumento, Strumento, registra

ESCLUSI = ESCLUSE
LIMITE_MASSIMO = 100


# ---------- viste e campi ----------

def _ambito(contesto):
    return getattr(contesto.conversazione, "ambito", "") or ""


def viste(contesto):
    """Le viste che l'utente può vedere (personalizzate per la sua richiesta), in ordine stabile."""
    return viste_accessibili(richiesta.per(contesto), modulo=_ambito(contesto))


def vista_per(contesto, nome):
    for v in viste(contesto):
        if id_vista(v) == nome:
            return v
    raise ErroreStrumento(f"Vista «{nome}» inesistente o non accessibile: usa elenco_viste per i nomi validi.")


def _ammesso(metodo):
    """I bottoni e le azioni con `ai = False` (download, stampe...) non li vede l'assistente."""
    return getattr(metodo, "ai", True) is not False


# ---------- valori ----------

def valore(obj, f):
    """Il valore di un campo in forma leggibile e serializzabile."""
    if f.many_to_many:
        return [{"id": o.pk, "nome": str(o)} for o in getattr(obj, f.name).all()[:50]]
    if f.is_relation:
        rel = getattr(obj, f.name)
        return {"id": rel.pk, "nome": str(rel)} if rel is not None else None
    v = getattr(obj, f.attname)
    if isinstance(v, datetime.datetime):
        return timezone.localtime(v).strftime("%Y-%m-%d %H:%M") if timezone.is_aware(v) else v.isoformat()
    if isinstance(v, (datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "field") and hasattr(v, "name"):                      # FieldFile
        return v.name or ""
    return v


def _url(vista, obj):
    try:
        return vista.url("dettaglio", pk=obj.pk)
    except Exception:
        return ""


def record(vista, obj, campi):
    dati = {"id": obj.pk, "nome": str(obj), "url": _url(vista, obj)}
    for f in campi:
        if f.name != "id":
            dati[f.name] = valore(obj, f)
    if getattr(obj, "proprieta", None):
        dati["campi_personalizzati"] = dict(obj.proprieta)
    return dati


def scelte(campi):
    """{campo: {codice: etichetta}} dei campi con scelte (i record riportano il codice)."""
    return {f.name: {str(k): str(v) for k, v in f.flatchoices} for f in campi if f.choices}


def _campi_elenco(vista, richiesti, request=None):
    leggibili = {f.name: f for f in campi_leggibili(vista, request)}
    if richiesti:
        mancanti = [c for c in richiesti if c not in leggibili]
        if mancanti:
            raise ErroreStrumento(f"Campi inesistenti o non leggibili: {', '.join(mancanti)}.")
        return [leggibili[c] for c in richiesti]
    scelti = [leggibili[c] for c in vista.list_display if c in leggibili]
    return scelti or list(leggibili.values())[:8]


def _ottimizza(qs, campi):
    relazioni = [f.name for f in campi if f.is_relation and not f.many_to_many]
    multiple = [f.name for f in campi if f.many_to_many]
    return qs.select_related(*relazioni).prefetch_related(*multiple)


def _ordina(vista, qs, ordina):
    if not ordina:
        return qs
    lookup, f, _ = _percorso(vista, ordina.lstrip("-"), con_operatore=False)
    if f.many_to_many:
        raise ErroreStrumento("Non si ordina per un campo con più valori.")
    return qs.order_by(f"-{lookup}" if ordina.startswith("-") else lookup, "pk")


# ---------- strumenti ----------

def elenco_viste(contesto, app=""):
    elenco = [{"vista": id_vista(v), "nome": str(v.verbose_name_plural), "app": v.modulo,
               **({"contiene": v.ai_descrizione} if v.ai_descrizione else {})} for v in viste(contesto)
              if not app or v.modulo == app]
    if not elenco:
        return "Nessuna vista accessibile" + (f" nell'app «{app}»." if app else ".")
    return elenco


def _tipo(f):
    if f.many_to_many:
        return "più record"
    if f.is_relation:
        return "record"
    for classe, nome in [(models.BooleanField, "sì/no"), (models.DateTimeField, "data e ora"),
                         (models.DateField, "data"), (models.DecimalField, "decimale"), (models.FloatField, "decimale"),
                         (models.IntegerField, "intero"), (models.FileField, "file"), (models.JSONField, "JSON")]:
        if isinstance(f, classe):
            return nome
    return "testo"


def _descrivi_campo(f, modificabili):
    d = {"nome": f.name, "etichetta": str(f.verbose_name), "tipo": _tipo(f)}
    if f.is_relation:
        collegata = registry.per_modello(f.related_model)
        d["collegato_a"] = id_vista(collegata) if collegata else str(f.related_model._meta.verbose_name_plural)
    if f.choices:
        d["scelte"] = {str(k): str(v) for k, v in f.flatchoices}
    if f.name in modificabili:
        d["modificabile"] = True
        if not f.blank and not f.has_default() and not f.many_to_many:
            d["obbligatorio"] = True
    return d


def descrivi(vista, request):
    form_class = vista.get_form_class(request)
    modificabili = set(form_class.base_fields)
    risultato = {
        "vista": id_vista(vista), "nome": str(vista.verbose_name_plural), "app": vista.modulo,
        "campi": [_descrivi_campo(f, modificabili) for f in campi_leggibili(vista, request)],
        "ricerca_libera_su": list(vista.search_fields),
        "raggruppamenti_suggeriti": list(vista.list_group_by),
        "campi_sommabili": list(vista.list_sum),
        "permessi": {"crea": vista.has_add_permission(request), "modifica": vista.has_change_permission(request),
                     "elimina": vista.has_delete_permission(request)},
        "bottoni_del_record": [{"nome": n, "etichetta": str(e),
                                "rischio": getattr(getattr(vista, n), "rischio", "scrittura")}
                               for n, e in ((n, vista.etichetta_metodo(n)) for n in vista.buttons)
                               if vista.permesso_metodo(request, getattr(vista, n)) and _ammesso(getattr(vista, n))],
        "azioni_su_piu_record": [{"nome": n, "etichetta": str(e)} for n, e in vista.get_actions(request)
                                 if _ammesso(getattr(vista, n))],
    }
    personalizzati = [{"nome": d.nome, "etichetta": d.label, "tipo": d.tipo} for d in vista.proprieta(request)]
    if personalizzati:
        risultato["campi_personalizzati"] = personalizzati
    if vista.inlines:
        inline = vista.inlines[0]
        risultato["righe"] = {"titolo": inline.titolo, "campi": [_descrivi_campo(inline.model._meta.get_field(c),
                                                                                set(inline.fields))
                                                                for c in inline.fields]}
    return risultato


def descrivi_vista(contesto, vista):
    return descrivi(vista_per(contesto, vista), richiesta.per(contesto))


def cerca(vista, request, testo="", filtri=None, ordina="", limite=20, pagina=1, campi=None):
    try:
        limite, pagina = max(1, min(int(limite), LIMITE_MASSIMO)), max(1, int(pagina))
    except (TypeError, ValueError):
        raise ErroreStrumento("«limite» e «pagina» devono essere numeri interi.")
    scelti = _campi_elenco(vista, campi, request)
    qs = _ordina(vista, filtra(vista, request, vista.get_queryset(request), testo, filtri), ordina)
    totale = qs.count()
    righe = _ottimizza(qs, scelti)[(pagina - 1) * limite:pagina * limite]
    risultato = {"vista": id_vista(vista), "totale": totale, "pagina": pagina,
                 "risultati": [record(vista, o, scelti) for o in righe]}
    if s := scelte(scelti):
        risultato["scelte"] = s
    if totale > pagina * limite:
        risultato["nota"] = f"Mostrati {len(risultato['risultati'])} su {totale}: chiedi la pagina {pagina + 1} " \
                            "o restringi i filtri. Per conteggi e totali usa aggrega_record."
    return risultato


def cerca_record(contesto, vista, testo="", filtri=None, ordina="", limite=20, pagina=1, campi=None):
    return cerca(vista_per(contesto, vista), richiesta.per(contesto), testo, filtri, ordina, limite, pagina, campi)


def oggetto(vista, request, pk):
    try:
        return vista.get_object(request, int(pk))
    except (Http404, TypeError, ValueError):
        raise ErroreStrumento(f"Record {pk} non trovato in {id_vista(vista)} (o non visibile per l'azienda corrente).")


def leggi_record(contesto, vista, id):
    v, request = vista_per(contesto, vista), richiesta.per(contesto)
    obj = oggetto(v, request, id)
    campi = campi_leggibili(v, request)
    risultato = record(v, obj, campi)
    if s := scelte(campi):
        risultato["scelte"] = s
    for inline in v.inlines:
        campi_righe = [inline.model._meta.get_field(c) for c in inline.fields]
        righe = _ottimizza(inline.model._default_manager.filter(**{inline.fk: obj}).order_by("pk"), campi_righe)
        risultato.setdefault("righe", {})[inline.titolo] = [
            {"id": r.pk, **{f.name: valore(r, f) for f in campi_righe}} for r in righe[:200]]
    if totali := v.totali(obj):
        risultato["totali"] = {str(e): str(val) for e, val in totali}
    if bottoni := [(n, e) for n, e in v.get_buttons(request, obj) if _ammesso(getattr(v, n))]:
        risultato["bottoni_disponibili"] = [{"nome": n, "etichetta": str(e)} for n, e in bottoni]
    return risultato


def aggrega_record(contesto, vista, per="", misura="count", filtri=None, testo="", aziende=None):
    from core.viste.interroga import aziende_di
    request = richiesta.per(contesto)
    return aggrega(vista_per(contesto, vista), request, per, misura, filtri, testo, aziende=aziende_di(request, aziende))


# ---------- registrazione ----------

VISTA = {"type": "string", "description": "nome della vista come in elenco_viste, es. vendite.ordini"}
FILTRI = {"type": "object", "description": "filtri {campo: valore}; operatori con __: gte, lte, gt, lt, in (lista), "
                                           "icontains, istartswith, isnull, year, month. Un salto su una relazione: "
                                           "cliente__nome__icontains. Date in formato AAAA-MM-GG.",
          "additionalProperties": True}
TESTO = {"type": "string", "description": "ricerca libera (nomi, numeri di documento...)"}

registra(Strumento(
    "elenco_viste", "Le viste (tabelle di dati) delle app che l'utente può consultare, con il nome da usare negli "
                    "altri strumenti. Chiamalo prima di cercare dati se non conosci il nome della vista.",
    {"type": "object", "properties": {"app": {"type": "string", "description": "solo le viste di questa app (slug)"}},
     "required": []}, elenco_viste))
registra(Strumento(
    "descrivi_vista", "Campi di una vista (tipo, scelte possibili, collegamenti ad altre viste, quali si possono "
                      "modificare), filtri utili, permessi dell'utente, bottoni e azioni disponibili.",
    {"type": "object", "properties": {"vista": VISTA}, "required": ["vista"]}, descrivi_vista))
registra(Strumento(
    "cerca_record", "Cerca record in una vista con ricerca libera e filtri; restituisce i record con id, nome, link "
                    "e i campi principali (o quelli richiesti). Per contare o sommare usa aggrega_record.",
    {"type": "object", "properties": {
        "vista": VISTA, "testo": TESTO, "filtri": FILTRI,
        "ordina": {"type": "string", "description": "campo di ordinamento, con - davanti per decrescente"},
        "limite": {"type": "integer", "description": f"record per pagina (max {LIMITE_MASSIMO}, default 20)"},
        "pagina": {"type": "integer", "description": "pagina, da 1"},
        "campi": {"type": "array", "items": {"type": "string"}, "description": "campi da restituire (default: quelli "
                                                                                "della lista)"}},
     "required": ["vista"]}, cerca_record))
registra(Strumento(
    "leggi_record", "Tutti i campi di un record, con le righe del documento, i totali e i bottoni disponibili.",
    {"type": "object", "properties": {"vista": VISTA, "id": {"type": "integer"}}, "required": ["vista", "id"]},
    leggi_record))
registra(Strumento(
    "aggrega_record", "Conteggi, somme, medie, minimi e massimi calcolati nel database, in totale o per gruppo "
                      "(campo, relazione o data per giorno/mese/anno). Usalo per ogni numero di sintesi.",
    {"type": "object", "properties": {
        "vista": VISTA, "testo": TESTO, "filtri": FILTRI,
        "per": {"type": "string", "description": "raggruppa per campo (es. stato, cliente) o data (es. data:mese); "
                                                 "vuoto = solo il totale"},
        "misura": {"type": "string", "description": "count (default) oppure sum:campo, avg:campo, min:campo, "
                                                    "max:campo"},
        "aziende": {"description": "per il consolidato di più aziende dell'utente: \"tutte\" oppure una lista di id; "
                                   "vuoto = solo l'azienda corrente"}},
     "required": ["vista"]}, aggrega_record))
