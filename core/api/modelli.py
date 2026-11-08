"""Endpoint generati per ogni ModelView con api=True: /api/v1/<modulo>/<slug>/."""
import datetime
import json
import re

from django.conf import settings
from django.forms.models import model_to_dict
from django.http.response import HttpResponseBase
from ninja import Router
from ninja.errors import HttpError

from core.viste import filtri, registry

from . import api
from .auth import azienda_per, controlla_token

MAX_PER_PAGE = 200
SEGRETI = re.compile(r"cifrat|segret|secret|token|password|hash|impronta|^chiave$", re.I)


def campi_api(vista, request=None):
    """I campi del form e quelli in sola lettura che sono campi veri del modello; mai quelli che sembrano segreti né
    quelli nascosti per il ruolo di chi chiama (core.regole)."""
    if request is not None:
        from core import regole
        via = regole.nascosti(vista, request)
        if via:
            return [c for c in campi_api(vista) if c not in via]
    if vista.api_fields:
        return list(vista.api_fields)
    campi = vista.campi_form() + [c for c in vista.readonly_fields if c not in vista.campi_form()]
    if vista.company_field and vista.company_field not in campi:
        campi.append(vista.company_field)
    veri = {f.name for f in vista.opts.get_fields()
            if getattr(f, "concrete", False) or (f.many_to_many and not f.auto_created)}
    return [c for c in campi if c in veri and not SEGRETI.search(c)]


def _tipo(f):
    """Lo schema JSON di un campo, com'è in serializza (le DecimalField escono come testo)."""
    from django.db import models as m
    if f.many_to_many:
        return {"type": "array", "items": {"type": "integer"}}
    if f.is_relation:
        return {"type": ["integer", "null"], "description": f"id di {f.related_model._meta.verbose_name}"}
    if f.choices:
        return {"type": "string", "enum": [str(k) for k, _ in f.flatchoices]}
    for classe, schema in ((m.BooleanField, {"type": "boolean"}), (m.DateTimeField, {"type": "string", "format": "date-time"}),
                           (m.DateField, {"type": "string", "format": "date"}), (m.DecimalField, {"type": "string", "format": "decimal"}),
                           (m.IntegerField, {"type": "integer"}), (m.FloatField, {"type": "number"}),
                           (m.FileField, {"type": "string", "format": "uri"}), (m.JSONField, {})):
        if isinstance(f, classe):
            return dict(schema)
    return {"type": "string"}


def schema_record(vista, campi=None, in_uscita=True):
    """Lo schema JSON di un record della vista: per le risposte (con id e <fk>_display) o per il corpo di crea/modifica."""
    proprieta, obbligatori = ({"id": {"type": "integer", "readOnly": True}} if in_uscita else {}), []
    for nome in campi if campi is not None else campi_api(vista):
        try:
            f = vista.opts.get_field(nome)
        except Exception:                                  # noqa: BLE001 - non è un campo del modello
            continue
        if f.auto_created and not f.concrete:              # relazione inversa
            continue
        voce = _tipo(f)
        voce["title"] = str(f.verbose_name)
        if f.help_text:
            voce["description"] = str(f.help_text)
        proprieta[nome] = voce
        if in_uscita and f.is_relation and not f.many_to_many:
            proprieta[f"{nome}_display"] = {"type": "string", "readOnly": True}
        if not in_uscita and not f.blank and not f.has_default() and not f.many_to_many:
            obbligatori.append(nome)
    if hasattr(vista.model, "proprieta"):
        proprieta["proprieta"] = {"type": "object", "description": "campi personalizzati dell'azienda"}
    schema = {"type": "object", "properties": proprieta}
    if obbligatori:
        schema["required"] = obbligatori
    return schema


def _json(schema):
    return {"content": {"application/json": {"schema": schema}}}


def serializza(vista, obj, request=None):
    """dict: id, campi di api_fields; FK come id più <fk>_display; M2M come lista di id; date ISO;
    `proprieta` con i campi personalizzati se il modello li accetta."""
    dati = {"id": obj.pk}
    if hasattr(obj, "proprieta"):
        dati["proprieta"] = dict(obj.proprieta or {})
    for nome in campi_api(vista, request):
        f = vista.opts.get_field(nome)
        if f.many_to_many:
            dati[nome] = [o.pk for o in getattr(obj, nome).all()]
        elif f.is_relation:
            rel = getattr(obj, nome)
            dati[nome] = rel.pk if rel else None
            dati[f"{nome}_display"] = str(rel) if rel else ""
        else:
            valore = getattr(obj, nome)
            if isinstance(valore, (datetime.date, datetime.datetime)):
                valore = valore.isoformat()
            elif hasattr(valore, "field") and hasattr(valore, "name"):     # FieldFile
                valore = valore.url if valore else ""
            dati[nome] = valore
    return dati


def _dati_form(corpo):
    """Il corpo JSON come dati del form: le chiavi di `proprieta` diventano campi prop_<nome>."""
    proprieta = corpo.pop("proprieta", None) or {}
    return {**corpo, **{f"prop_{k}": v for k, v in proprieta.items()}} if isinstance(proprieta, dict) else corpo


def _corpo(request):
    try:
        dati = json.loads(request.body or b"{}")
    except ValueError:
        raise HttpError(400, "corpo JSON non valido")
    if not isinstance(dati, dict):
        raise HttpError(400, "atteso un oggetto JSON")
    return dati


def _errori(request, form):
    return api.create_response(request, {"errori": {k: [str(e) for e in v] for k, v in form.errors.items()}},
                               status=422)


def _router_per(vista):
    router = Router(tags=[f"{vista.modulo}.{vista.slug}"])
    op = f"{vista.modulo}_{vista.slug}"
    record = schema_record(vista)
    corpo = schema_record(vista, [c for c in vista.campi_form() if not SEGRETI.search(c)], in_uscita=False)
    errori = _json({"type": "object", "properties": {"errori": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}}}})
    doc_lista = {"responses": {200: {"description": "Una pagina di record", **_json({"type": "object", "properties": {
        "count": {"type": "integer"}, "page": {"type": "integer"}, "per_page": {"type": "integer"},
        "results": {"type": "array", "items": record}}})}}}
    doc_record = {"responses": {200: {"description": "Il record", **_json(record)}}}
    doc_crea = {"requestBody": {"required": True, **_json(corpo)},
                "responses": {201: {"description": "Creato", **_json(record)}, 422: {"description": "Dati non validi", **errori}}}
    doc_modifica = {"requestBody": {"required": True, **_json({**corpo, "required": []})},
                    "responses": {200: {"description": "Modificato", **_json(record)}, 422: {"description": "Dati non validi", **errori}}}

    def oggetto(request, pk, permesso, scrittura=True):
        controlla_token(request, vista.modulo, scrittura)
        azienda_per(request)
        obj = vista.get_object(request, pk)
        if not permesso(request, obj):
            raise HttpError(403, "permesso negato")
        return obj

    def salva(request, form, change):
        obj = form.save(commit=False)
        vista.save_model(request, obj, form, change=change)
        return serializza(vista, obj, request)

    @router.get("/", operation_id=f"{op}_lista", summary=f"Elenco di {vista.verbose_name_plural}", openapi_extra=doc_lista)
    def lista(request, q: str = "", o: str = "", p: int = 1, per_page: int = 50):
        controlla_token(request, vista.modulo, False)
        azienda_per(request)
        if not vista.has_view_permission(request):
            raise HttpError(403, "permesso negato")
        qs = filtri.applica(vista, request, vista.get_queryset(request))
        per_page = max(1, min(per_page, MAX_PER_PAGE))
        p = max(1, p)
        totale = qs.count()
        righe = qs[(p - 1) * per_page:p * per_page]
        return {"count": totale, "page": p, "per_page": per_page,
                "results": [serializza(vista, obj, request) for obj in righe]}

    @router.post("/", operation_id=f"{op}_crea", summary=f"Crea {vista.verbose_name}", openapi_extra=doc_crea)
    def crea(request):
        controlla_token(request, vista.modulo, True)
        azienda_per(request)
        if not vista.has_add_permission(request):
            raise HttpError(403, "permesso negato")
        form = vista.get_form_class(request)(data=_dati_form(_corpo(request)))
        if not form.is_valid():
            return _errori(request, form)
        return api.create_response(request, salva(request, form, change=False), status=201)

    @router.get("/{int:pk}/", operation_id=f"{op}_leggi", summary=f"Un record di {vista.verbose_name_plural}", openapi_extra=doc_record)
    def leggi(request, pk: int):
        return serializza(vista, oggetto(request, pk, vista.has_view_permission, scrittura=False), request)

    @router.patch("/{int:pk}/", operation_id=f"{op}_modifica", summary=f"Modifica {vista.verbose_name}", openapi_extra=doc_modifica)
    def modifica(request, pk: int):
        obj = oggetto(request, pk, vista.has_change_permission)
        form_class = vista.get_form_class(request)
        attuali = model_to_dict(obj, fields=list(form_class.base_fields))
        attuali.update({f"prop_{d.nome}": (obj.proprieta or {}).get(d.nome)       # PATCH: le proprietà non date restano
                        for d in getattr(form_class, "definizioni_proprieta", [])})
        form = form_class(data={**attuali, **_dati_form(_corpo(request))}, instance=obj)
        if not form.is_valid():
            return _errori(request, form)
        return salva(request, form, change=True)

    @router.post("/{int:pk}/azioni/{nome}/", operation_id=f"{op}_azione", summary=f"Bottone su {vista.verbose_name}")
    def azione(request, pk: int, nome: str):
        """Lo stesso bottone della pagina di dettaglio, con gli stessi permessi e controlli di stato."""
        obj = oggetto(request, pk, vista.has_view_permission)
        if nome not in {n for n, _ in vista.get_buttons(request, obj)}:
            raise HttpError(404, "azione non disponibile")
        esito = getattr(vista, nome)(request, obj)
        if isinstance(esito, HttpResponseBase):            # una stampa, un file
            return esito
        return {"esito": str(esito) if esito else "", "dati": serializza(vista, vista.get_object(request, pk), request)}

    @router.delete("/{int:pk}/", operation_id=f"{op}_elimina", summary=f"Elimina {vista.verbose_name}")
    def elimina(request, pk: int):
        oggetto(request, pk, vista.has_delete_permission).delete()
        return api.create_response(request, None, status=204)

    return router


registry.autodiscover(settings.ADDONS_ATTIVI)
for _modulo in ["core", *settings.ADDONS_ATTIVI]:
    for _vista in registry.viste_di(_modulo):
        if _vista.api:
            api.add_router(f"/{_vista.modulo}/{_vista.slug}", _router_per(_vista))
