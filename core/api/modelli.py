"""Endpoint generati per ogni ModelView con api=True: /api/v1/<modulo>/<slug>/."""
import datetime
import json

from django.conf import settings
from django.forms.models import model_to_dict
from ninja import Router
from ninja.errors import HttpError

from core.viste import filtri, registry

from . import api
from .auth import azienda_per

MAX_PER_PAGE = 200


def campi_api(vista):
    if vista.api_fields:
        return list(vista.api_fields)
    campi = vista.campi_form() + [c for c in vista.readonly_fields if c not in vista.campi_form()]
    if vista.company_field and vista.company_field not in campi:
        campi.append(vista.company_field)
    return campi


def serializza(vista, obj):
    """dict: id, campi di api_fields; FK come id più <fk>_display; M2M come lista di id; date ISO;
    `proprieta` con i campi personalizzati se il modello li accetta."""
    dati = {"id": obj.pk}
    if hasattr(obj, "proprieta"):
        dati["proprieta"] = dict(obj.proprieta or {})
    for nome in campi_api(vista):
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

    def oggetto(request, pk, permesso):
        azienda_per(request)
        obj = vista.get_object(request, pk)
        if not permesso(request, obj):
            raise HttpError(403, "permesso negato")
        return obj

    def salva(request, form, change):
        obj = form.save(commit=False)
        vista.save_model(request, obj, form, change=change)
        return serializza(vista, obj)

    @router.get("/", operation_id=f"{op}_lista", summary=f"Elenco di {vista.verbose_name_plural}")
    def lista(request, q: str = "", o: str = "", p: int = 1, per_page: int = 50):
        azienda_per(request)
        if not vista.has_view_permission(request):
            raise HttpError(403, "permesso negato")
        qs = filtri.applica(vista, request, vista.get_queryset(request))
        per_page = max(1, min(per_page, MAX_PER_PAGE))
        p = max(1, p)
        totale = qs.count()
        righe = qs[(p - 1) * per_page:p * per_page]
        return {"count": totale, "page": p, "per_page": per_page,
                "results": [serializza(vista, obj) for obj in righe]}

    @router.post("/", operation_id=f"{op}_crea", summary=f"Crea {vista.verbose_name}")
    def crea(request):
        azienda_per(request)
        if not vista.has_add_permission(request):
            raise HttpError(403, "permesso negato")
        form = vista.get_form_class(request)(data=_dati_form(_corpo(request)))
        if not form.is_valid():
            return _errori(request, form)
        return api.create_response(request, salva(request, form, change=False), status=201)

    @router.get("/{int:pk}/", operation_id=f"{op}_leggi", summary=f"Un record di {vista.verbose_name_plural}")
    def leggi(request, pk: int):
        return serializza(vista, oggetto(request, pk, vista.has_view_permission))

    @router.patch("/{int:pk}/", operation_id=f"{op}_modifica", summary=f"Modifica {vista.verbose_name}")
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
