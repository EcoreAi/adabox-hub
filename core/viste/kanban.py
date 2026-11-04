"""Vista kanban: colonne dai valori di un campo (scelte o FK), card trascinabili tra le colonne."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import F, OuterRef, Subquery
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core import chatter
from core.colori import COLORI_COLONNE, iniziali, tinta_persona
from core.models import Messaggio, SpostamentoKanban

from . import filtri
from .lista import VistaBase, contesto_testata, urls_di

ULTIMO = "spostata"


def colonne(vista, request):
    """[(valore come stringa, etichetta)] delle colonne; per le FK anche 'Senza …' se il campo ammette vuoto."""
    f = vista.opts.get_field(vista.kanban_group)
    if f.choices:
        valori = [(str(k), str(v)) for k, v in f.flatchoices]
    else:
        qs = f.related_model._default_manager.all()
        azienda = getattr(request, "azienda", None)
        if azienda is not None and any(c.name == "azienda" for c in f.related_model._meta.get_fields()):
            qs = qs.filter(azienda=azienda)
        valori = [(str(o.pk), str(o)) for o in qs[:50]]
    if f.null and not f.choices:
        valori.insert(0, ("", f"Senza {f.verbose_name}"))
    return valori


def _filtro(vista, valore):
    f = vista.opts.get_field(vista.kanban_group)
    if valore == "":
        return {f"{vista.kanban_group}__isnull": True}
    return {vista.kanban_group: valore}


def _chiuse(vista):
    """Le colonne che partono ripiegate: quelle finite, che servono meno e di solito sono le più lunghe."""
    f = vista.opts.get_field(vista.kanban_group)
    if f.choices:
        return {str(v) for v in vista.kanban_valori_chiusi}
    campi = {c.name for c in f.related_model._meta.get_fields()}
    for nome in ("chiusa", "vinta"):
        if nome in campi:
            return {str(pk) for pk in f.related_model._default_manager.filter(**{nome: True}).values_list("pk", flat=True)}
    return set()


def _ordini(vista):
    return [("", "Ordine predefinito"), *vista.kanban_ordini, ("-pk", "Più recenti"), (ULTIMO, "Ultimo spostamento")]


def _ordina(vista, qs, scelta, chiusa):
    if scelta == ULTIMO:
        ultimo = SpostamentoKanban.objects.filter(content_type=ContentType.objects.get_for_model(vista.model), object_id=OuterRef("pk")).values("quando")[:1]
        return qs.annotate(_spostata=Subquery(ultimo)).order_by(F("_spostata").desc(nulls_last=True), "pk")
    if scelta and scelta in dict(_ordini(vista)):
        return qs.order_by(scelta, "pk")
    return qs.order_by(vista.kanban_ordine_chiuse, "pk") if chiusa and vista.kanban_ordine_chiuse else qs


def _spostamenti(vista, oggetti):
    """{pk: l'ultimo spostamento} per le card mostrate, con una query sola."""
    risultato = {}
    for s in SpostamentoKanban.objects.filter(content_type=ContentType.objects.get_for_model(vista.model),
                                              object_id__in=[o.pk for o in oggetti]).select_related("utente"):
        risultato.setdefault(s.object_id, s)
    return risultato


def _dati_spostamento(s):
    if s is None:
        return None
    u = s.utente
    return {"nome": (u.get_full_name() or u.get_username()) if u else "Qualcuno", "iniziali": iniziali(u) if u else "?", "tinta": tinta_persona(u.pk) if u else "grigio",
            "da": s.da, "a": s.a, "quando": s.quando, "nota": s.nota}


def _card(vista, request, oggetti):
    ultimi = _spostamenti(vista, oggetti)
    return [{"obj": obj, "scheda": vista.kanban_scheda(request, obj) if vista.kanban_ricco else None,
             "campi": [] if vista.kanban_ricco else [(vista.etichetta(c), vista.col_valore(request, obj, c)) for c in vista.kanban_fields],
             "spostato": _dati_spostamento(ultimi.get(obj.pk))} for obj in oggetti]


def _base_card(vista, request):
    """Quello che serve al template di una card."""
    return {"vista": vista, "tutte": colonne(vista, request), "puo_spostare": vista.has_change_permission(request) and vista.kanban_spostabile(),
            "query_filtri": contesto_testata(request, vista, "kanban").get("query_filtri", "")}


class KanbanView(VistaBase):
    def get(self, request):
        vista = self.vista
        if not vista.has_view_permission(request):
            raise PermissionDenied
        qs = filtri.applica(vista, request, vista.get_queryset(request))
        if "card" in request.GET:
            return self._una_card(request, qs)
        if "colonna" in request.GET:
            return self._altre_card(request, qs)
        chiuse = _chiuse(vista)
        cols = []
        valori = colonne(vista, request)
        for posizione, (valore, etichetta) in enumerate(valori):
            col_qs = qs.filter(**_filtro(vista, valore))
            totale = col_qs.count()
            righe = vista.kanban_queryset(col_qs) if vista.kanban_ricco else col_qs
            card = _card(vista, request, list(_ordina(vista, righe, "", valore in chiuse)[:vista.kanban_limite]))
            extra = dict(vista.kanban_colonna(request, valore, col_qs)) if vista.kanban_ricco else {}
            if vista.kanban_ricco and "colore" not in extra:
                extra["colore"] = vista.kanban_colori.get(valore) or ("grigio" if valore == "" else COLORI_COLONNE[posizione % len(COLORI_COLONNE)])
            cols.append({"valore": valore, "etichetta": etichetta, "totale": totale, "card": card, "ripiegata": valore in chiuse,
                         "altri": totale - len(card), "extra": extra})
        testata = contesto_testata(request, vista, "kanban")
        return render(request, vista.template_kanban, {
            "vista": vista, "urls": urls_di(vista), "colonne": cols, "tutte": valori, "ordini": _ordini(vista),
            "filtri": filtri.specifiche(vista, request), "puo_aggiungere": vista.has_add_permission(request),
            "puo_spostare": vista.has_change_permission(request) and vista.kanban_spostabile(), "campo": vista.kanban_group, "extra_get": [],
            **testata})

    def _altre_card(self, request, qs):
        """Un pezzo di colonna: scorrendo (`da`) o cambiando ordinamento (`ordine`). Quante ne restano in X-Altri."""
        vista = self.vista
        valore, da = request.GET.get("colonna", ""), request.GET.get("da", "0")
        if valore not in dict(colonne(vista, request)):
            return HttpResponseBadRequest("colonna non valida")
        da = int(da) if da.isdigit() else 0
        col_qs = qs.filter(**_filtro(vista, valore))
        righe = vista.kanban_queryset(col_qs) if vista.kanban_ricco else col_qs
        oggetti = list(_ordina(vista, righe, request.GET.get("ordine", ""), valore in _chiuse(vista))[da:da + vista.kanban_limite])
        risposta = render(request, "core/vista/_carte_kanban.html", {**_base_card(vista, request), "col": {"valore": valore, "card": _card(vista, request, oggetti)}})
        risposta["X-Altri"] = max(col_qs.count() - da - len(oggetti), 0)
        return risposta

    def _una_card(self, request, qs):
        """Una card sola, ridisegnata dopo uno spostamento o una nota."""
        vista = self.vista
        righe = vista.kanban_queryset(qs) if vista.kanban_ricco else qs
        obj = righe.filter(pk=request.GET["card"] if request.GET["card"].isdigit() else None).first()
        if obj is None:
            return HttpResponse(status=404)
        valore = getattr(obj, vista.opts.get_field(vista.kanban_group).attname)
        return render(request, "core/vista/_card_kanban.html", {**_base_card(vista, request), "c": _card(vista, request, [obj])[0], "col": {"valore": "" if valore is None else str(valore)}})


class SpostaView(VistaBase):
    """Cambia il valore del campo di raggruppamento (colonna) di un record: permesso change, tracciamento."""
    http_method_names = ["post"]

    def post(self, request, pk):
        vista = self.vista
        obj = vista.get_object(request, pk)
        if not vista.has_change_permission(request, obj) or not vista.kanban_spostabile():
            raise PermissionDenied
        valore = request.POST.get("valore", "")
        if valore not in dict(colonne(vista, request)):
            return HttpResponseBadRequest("colonna non valida")
        campo = vista.opts.get_field(vista.kanban_group)
        etichette = dict(colonne(vista, request))
        prima = getattr(obj, campo.attname)
        prima = "" if prima is None else str(prima)
        tracciati = list(vista.tracked_fields) if vista.chatter else []
        vecchi = chatter.valori(obj, tracciati) if tracciati else None
        if campo.choices:
            setattr(obj, campo.name, valore)
        else:
            setattr(obj, campo.attname, int(valore) if valore else None)
        if motivo := vista.kanban_vietato(request, obj):
            if request.headers.get("HX-Request"):
                return HttpResponse(motivo, status=409, content_type="text/plain; charset=utf-8")
            messages.error(request, motivo)
            return redirect(vista.url("kanban"))
        obj.save(update_fields=[campo.name])
        if vecchi is not None:
            chatter.traccia(obj, vecchi, request.user)
        spostamento = None
        if prima != valore:
            spostamento = SpostamentoKanban.objects.create(content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk, utente=request.user,
                                                           da=etichette.get(prima, "")[:120], a=etichette.get(valore, "")[:120])
        if request.headers.get("HX-Request"):
            risposta = HttpResponse(status=204)
            if spostamento:
                risposta["X-Nota"] = reverse("core:kanban_nota", args=[spostamento.pk])
            return risposta
        messages.success(request, f"«{obj}» spostato.")
        return redirect(vista.url("kanban") + (f"?{request.POST['ritorno']}" if request.POST.get("ritorno") else ""))


@login_required
@require_POST
def nota(request, pk):
    """La nota allo spostamento appena fatto: solo di chi l'ha fatto. Va anche nello storico del record, se ne ha uno."""
    from . import registry
    s = get_object_or_404(SpostamentoKanban, pk=pk, utente=request.user)
    testo = request.POST.get("nota", "").strip()[:2000]
    if not testo:
        return HttpResponseBadRequest("nota vuota")
    s.nota = testo
    s.save(update_fields=["nota"])
    modello = s.content_type.model_class()
    vista = registry.per_modello(modello) if modello else None
    obj = modello._default_manager.filter(pk=s.object_id).first() if modello else None
    if obj is not None and vista is not None and vista.chatter:
        chatter.scrivi(obj, request.user, corpo=f"{s.da} → {s.a}: {testo}", tipo=Messaggio.NOTA)
    return HttpResponse(status=204)
