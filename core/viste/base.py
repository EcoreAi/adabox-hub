"""ModelView: viste di un modello dichiarate in Python, sullo stile di ModelAdmin."""
from django.db import transaction
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404
from django.urls import path, reverse

from . import widgets


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
    form_layout = None            # [("Sezione", ["campo", ("affiancato1", "affiancato2")]), ...]
    form_class = None
    readonly_fields = ()
    company_field = None          # None = modello globale
    sequence_field = None         # ("campo", "modulo.codice"): numero assegnato alla creazione
    actions = ()                  # nomi di metodi (self, request, queryset) -> str|None
    buttons = ()                  # nomi di metodi (self, request, obj) -> HttpResponse|str|None
    api = False
    api_fields = None
    template_lista = "core/vista/lista.html"
    template_tabella = "core/vista/_tabella.html"
    template_form = "core/vista/form.html"
    template_dettaglio = "core/vista/dettaglio.html"
    template_conferma = "core/vista/_conferma.html"

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
        from . import azioni, dettaglio, elimina, form, lista
        s = self.slug
        return [
            path(f"{s}/", lista.ListaView.as_view(vista=self), name=f"{s}_lista"),
            path(f"{s}/nuovo/", form.FormView.as_view(vista=self), name=f"{s}_nuovo"),
            path(f"{s}/<int:pk>/", dettaglio.DettaglioView.as_view(vista=self), name=f"{s}_dettaglio"),
            path(f"{s}/<int:pk>/modifica/", form.FormView.as_view(vista=self), name=f"{s}_modifica"),
            path(f"{s}/<int:pk>/elimina/", elimina.EliminaView.as_view(vista=self), name=f"{s}_elimina"),
            path(f"{s}/azione/<slug:nome>/", azioni.AzioneView.as_view(vista=self), name=f"{s}_azione"),
            path(f"{s}/<int:pk>/bottone/<slug:nome>/", azioni.BottoneView.as_view(vista=self), name=f"{s}_bottone"),
        ]

    def get_queryset(self, request):
        qs = self.model._default_manager.all()
        if self.company_field and getattr(request, "azienda", None) is not None:
            qs = qs.filter(**{self.company_field: request.azienda})
        if self.ordering:
            return qs.order_by(*self.ordering)
        return qs if qs.ordered else qs.order_by("pk")    # paginazione stabile

    def get_object(self, request, pk):
        return get_object_or_404(self.get_queryset(request), pk=pk)     # fuori azienda → 404

    def save_model(self, request, obj, form, change):
        if not change and self.company_field and getattr(obj, f"{self.company_field}_id", None) is None:
            setattr(obj, self.company_field, request.azienda)
        with transaction.atomic():
            if not change and self.sequence_field and not getattr(obj, self.sequence_field[0]):
                from core import sequenze
                azienda = getattr(obj, self.company_field) if self.company_field else None
                setattr(obj, self.sequence_field[0], sequenze.prossimo(self.sequence_field[1], azienda))
            obj.save()
            form.save_m2m()

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
        presenti = {c for _, righe in layout for riga in righe for c in riga}
        if mancanti := [c for c in self.readonly_fields if c not in presenti]:
            layout.append(("Altre informazioni", [[c] for c in mancanti]))
        return layout

    def campi_form(self):
        return [c for _, righe in self.layout() for riga in righe for c in riga if c not in self.readonly_fields]

    def get_form_class(self):
        return self.form_class or modelform_factory(self.model, fields=self.campi_form())

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
        metodo = getattr(self, f"col_{campo}", None)
        return metodo(obj) if metodo else widgets.rendi(self, obj, campo, request)
