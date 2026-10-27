"""ModelView: viste di un modello dichiarate in Python, sullo stile di ModelAdmin."""
from django.db import models, transaction
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404
from django.urls import NoReverseMatch, path, reverse

from . import widgets


def _campo_form(campo, **kwargs):
    """Campi del form generato: gli URL senza schema diventano https (comportamento di Django 6)."""
    if isinstance(campo, models.URLField):
        kwargs.setdefault("assume_scheme", "https")
    return campo.formfield(**kwargs)


def form_per_azienda(base, azienda_id):
    """Sottoclasse del form in cui le scelte di FK e M2M verso modelli per azienda (con il campo `azienda`)
    sono limitate all'azienda corrente: un record di un'altra azienda non si può né vedere né collegare."""
    if azienda_id is None:
        return base

    def __init__(self, *args, **kwargs):
        base.__init__(self, *args, **kwargs)
        for campo in self.fields.values():
            queryset = getattr(campo, "queryset", None)
            if queryset is not None and any(f.name == "azienda" and f.is_relation
                                            for f in queryset.model._meta.get_fields()):
                campo.queryset = queryset.filter(azienda_id=azienda_id)

    return type(base)(base.__name__, (base,), {"__init__": __init__, "__module__": base.__module__})


class ModelView:
    model = None
    slug = None
    verbose_name = None
    verbose_name_plural = None
    list_display = ("__str__",)
    list_filter = ()
    search_fields = ()
    ordering = ()
    per_page = 50
    list_group_by = ()            # raggruppamenti ammessi: "campo", "data:mese", "data:anno"
    list_sum = ()                 # campi numerici con i totali (per gruppo e in fondo)
    kanban_group = None           # vista kanban: campo con scelte o FK
    kanban_fields = ()            # campi mostrati nella card (oltre al titolo)
    kanban_limite = 50            # card per colonna
    calendar_date = None          # vista calendario: campo data
    calendar_color = None         # campo con scelte che colora gli eventi
    graph = None                  # vista grafico: {"tipi": [...], "misure": [...], "per": [...]}
    form_layout = None            # [("Sezione", ["campo", ("affiancato1", "affiancato2")]), ...]
    form_class = None
    readonly_fields = ()
    company_field = None          # None = modello globale
    sequence_field = None         # ("campo", "modulo.codice"): numero assegnato alla creazione
    chatter = False               # pannello messaggi/note/allegati/attività nel dettaglio
    tracked_fields = ()           # campi le cui modifiche finiscono nel chatter
    actions = ()                  # nomi di metodi (self, request, queryset) -> str|None
    buttons = ()                  # nomi di metodi (self, request, obj) -> HttpResponse|str|None
    api = False
    api_fields = None
    export_fields = None          # colonne dell'export (default: id + campi di list_display)
    import_key = None             # campo con cui l'import riconosce i record da aggiornare
    reports = ()                  # stampe PDF: [{"nome": "Scheda", "template": "app/report/x.html"}]
    template_lista = "core/vista/lista.html"
    template_tabella = "core/vista/_tabella.html"
    template_form = "core/vista/form.html"
    template_dettaglio = "core/vista/dettaglio.html"
    template_conferma = "core/vista/_conferma.html"
    template_kanban = "core/vista/kanban.html"
    template_calendario = "core/vista/calendario.html"

    def __init__(self, modulo):
        self.modulo = modulo                                   # namespace URL = slug del modulo
        self.opts = self.model._meta
        self.slug = self.slug or self.opts.model_name
        self.verbose_name = self.verbose_name or self.opts.verbose_name
        self.verbose_name_plural = self.verbose_name_plural or self.opts.verbose_name_plural

    def __repr__(self):
        return f"<{type(self).__name__} {self.modulo}:{self.slug}>"

    def nome_url(self, azione):
        return f"{self.modulo}:{self.slug}_{azione}"

    def url(self, azione, **kwargs):
        return reverse(self.nome_url(azione), kwargs=kwargs or None)

    def get_urls(self):
        from . import azioni, dettaglio, elimina, esporta, form, importa, lista
        s = self.slug
        return [
            path(f"{s}/", lista.ListaView.as_view(vista=self), name=f"{s}_lista"),
            path(f"{s}/nuovo/", form.FormView.as_view(vista=self), name=f"{s}_nuovo"),
            path(f"{s}/<int:pk>/", dettaglio.DettaglioView.as_view(vista=self), name=f"{s}_dettaglio"),
            path(f"{s}/<int:pk>/modifica/", form.FormView.as_view(vista=self), name=f"{s}_modifica"),
            path(f"{s}/<int:pk>/elimina/", elimina.EliminaView.as_view(vista=self), name=f"{s}_elimina"),
            path(f"{s}/azione/<slug:nome>/", azioni.AzioneView.as_view(vista=self), name=f"{s}_azione"),
            path(f"{s}/<int:pk>/bottone/<slug:nome>/", azioni.BottoneView.as_view(vista=self), name=f"{s}_bottone"),
            path(f"{s}/esporta/", esporta.EsportaView.as_view(vista=self), name=f"{s}_esporta"),
            path(f"{s}/importa/", importa.ImportaView.as_view(vista=self), name=f"{s}_importa"),
        ] + self.get_urls_viste()

    def get_urls_viste(self):
        """URL delle viste facoltative, solo se dichiarate."""
        from . import calendario, grafico, kanban, stampa
        s = self.slug
        urls = []
        if self.reports:
            urls += [path(f"{s}/<int:pk>/stampa/<int:indice>/", stampa.StampaView.as_view(vista=self), name=f"{s}_stampa"),
                     path(f"{s}/stampa/<int:indice>/", stampa.StampaMassaView.as_view(vista=self), name=f"{s}_stampa_massa")]
        if self.graph:
            urls.append(path(f"{s}/grafico/", grafico.GraficoView.as_view(vista=self), name=f"{s}_grafico"))
        if self.calendar_date:
            urls.append(path(f"{s}/calendario/", calendario.CalendarioView.as_view(vista=self), name=f"{s}_calendario"))
        if self.kanban_group:
            urls += [path(f"{s}/kanban/", kanban.KanbanView.as_view(vista=self), name=f"{s}_kanban"),
                     path(f"{s}/<int:pk>/sposta/", kanban.SpostaView.as_view(vista=self), name=f"{s}_sposta")]
        return urls

    def viste_disponibili(self):
        """[(nome, etichetta, url)] delle viste dichiarate, per il selettore nella testata."""
        viste = [("lista", "Lista", self.url("lista"))]
        for nome, etichetta, attivo in [("kanban", "Kanban", self.kanban_group), ("calendario", "Calendario", self.calendar_date),
                                        ("grafico", "Grafico", self.graph)]:
            if attivo:
                try:
                    viste.append((nome, etichetta, self.url(nome)))
                except NoReverseMatch:          # dichiarata ma non montata
                    pass
        return viste

    def get_queryset(self, request):
        qs = self.model._default_manager.all()
        azienda_id = getattr(getattr(request, "azienda", None), "pk", None)    # lazy: può avvolgere None
        if self.company_field and azienda_id is not None:
            qs = qs.filter(**{f"{self.company_field}_id": azienda_id})
        if self.ordering:
            return qs.order_by(*self.ordering)
        return qs if qs.ordered else qs.order_by("pk")    # paginazione stabile

    def get_object(self, request, pk):
        return get_object_or_404(self.get_queryset(request), pk=pk)     # fuori azienda → 404

    def save_model(self, request, obj, form, change):
        if not change and self.company_field and getattr(obj, f"{self.company_field}_id", None) is None:
            setattr(obj, self.company_field, request.azienda)
        from core import chatter
        with transaction.atomic():
            vecchi = None
            if change and self.chatter and self.tracked_fields:
                # il form ha già modificato obj: i valori di prima si rileggono dal DB
                vecchi = chatter.valori(self.model._default_manager.get(pk=obj.pk), self.tracked_fields)
            if not change and self.sequence_field and not getattr(obj, self.sequence_field[0]):
                from core import sequenze
                azienda = getattr(obj, self.company_field) if self.company_field else None
                setattr(obj, self.sequence_field[0], sequenze.prossimo(self.sequence_field[1], azienda))
            if hasattr(form, "applica_proprieta"):
                form.applica_proprieta(obj)
            obj.save()
            form.save_m2m()
            if self.chatter and not change:
                chatter.scrivi(obj, request.user, "Record creato.", tipo="sistema")
                chatter.segui(obj, request.user)
            elif vecchi is not None:
                chatter.traccia(obj, vecchi, request.user)

    def _perm(self, request, azione):
        return request.user.has_perm(f"{self.opts.app_label}.{azione}_{self.opts.model_name}")

    def has_view_permission(self, request, obj=None):
        return self._perm(request, "view")

    def has_add_permission(self, request):
        return self._perm(request, "add")

    def has_change_permission(self, request, obj=None):
        return self._perm(request, "change")

    def has_delete_permission(self, request, obj=None):
        return self._perm(request, "delete")

    def permesso_metodo(self, request, metodo):
        """Permesso di un'azione o di un bottone: attributo `permission` del metodo ('change' di default,
        oppure 'view'/'add'/'delete', oppure un permesso completo 'app.codename')."""
        perm = getattr(metodo, "permission", "change")
        return request.user.has_perm(perm) if "." in perm else self._perm(request, perm)

    def etichetta_metodo(self, nome):
        return getattr(getattr(self, nome), "short_description", nome.replace("_", " ").capitalize())

    def get_actions(self, request):
        """[(nome, etichetta)] delle azioni di massa che l'utente può usare."""
        return [(n, self.etichetta_metodo(n)) for n in self.actions if self.permesso_metodo(request, getattr(self, n))]

    def get_buttons(self, request, obj):
        """[(nome, etichetta)] dei bottoni del dettaglio che l'utente può usare."""
        return [(n, self.etichetta_metodo(n)) for n in self.buttons if self.permesso_metodo(request, getattr(self, n))]

    def layout(self):
        """form_layout normalizzato: [(titolo, [[campo, ...], ...])], ogni riga una lista di campi."""
        if self.form_layout is None:
            campi = [f.name for f in self.opts.get_fields()
                     if getattr(f, "editable", False) and not f.auto_created and f.name not in self.readonly_fields
                     and f.name != self.company_field]
            return [("", [[c] for c in campi])]
        return [(titolo, [list(r) if isinstance(r, (tuple, list)) else [r] for r in righe])
                for titolo, righe in self.form_layout]

    def layout_dettaglio(self):
        """Il layout più i readonly_fields che non vi compaiono."""
        layout = self.layout()
        presenti = {c for _, righe in layout for riga in righe for c in riga if not c.startswith("@")}
        if mancanti := [c for c in self.readonly_fields if c not in presenti]:
            layout.append(("Altre informazioni", [[c] for c in mancanti]))
        return layout

    def campi_form(self):
        return [c for _, righe in self.layout() for riga in righe for c in riga
                if c not in self.readonly_fields and not c.startswith("@")]

    def get_form_class(self, request=None):
        """ModelForm della vista; con la richiesta aggiunge i campi personalizzati validi per l'azienda corrente."""
        from core import proprieta
        base = self.form_class or modelform_factory(self.model, fields=self.campi_form(),
                                                    formfield_callback=_campo_form)
        if request is None:
            return base
        if proprieta.accetta(self.model):
            definizioni = proprieta.definizioni(self.model, getattr(request, "azienda", None))
            if definizioni:
                base = proprieta.form_con_proprieta(base, definizioni)
        return form_per_azienda(base, getattr(getattr(request, "azienda", None), "pk", None))

    def destinatari_esterni(self, obj):
        """Indirizzi email non utenti che ricevono i messaggi del chatter di `obj` e possono rispondere
        (es. il cliente di un ticket). Default nessuno."""
        return []

    def proprieta(self, request):
        """Definizioni dei campi personalizzati per l'azienda della richiesta ([] se il modello non li accetta)."""
        from core import proprieta
        return proprieta.definizioni(self.model, getattr(request, "azienda", None))

    def etichetta(self, campo):
        """Intestazione di colonna o etichetta di campo."""
        metodo = getattr(self, f"col_{campo}", None)
        if metodo is not None and hasattr(metodo, "short_description"):
            return metodo.short_description
        if campo == "__str__":
            return self.verbose_name[:1].upper() + self.verbose_name[1:]
        try:
            nome = str(self.opts.get_field(campo).verbose_name)
        except Exception:
            nome = campo.replace("_", " ")
        return nome[:1].upper() + nome[1:]

    def col_valore(self, request, obj, campo):
        if campo.startswith("prop_"):
            from core import proprieta
            d = next((d for d in self.proprieta(request) if proprieta.nome_campo(d) == campo), None)
            return proprieta.testo(d, obj) if d else "—"
        metodo = getattr(self, f"col_{campo}", None)
        return metodo(obj) if metodo else widgets.rendi(self, obj, campo, request)
