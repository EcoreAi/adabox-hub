"""ModelView: viste di un modello dichiarate in Python, sullo stile di ModelAdmin."""
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
        return qs.order_by(*self.ordering) if self.ordering else qs

    def get_object(self, request, pk):
        return get_object_or_404(self.get_queryset(request), pk=pk)     # fuori azienda → 404

    def save_model(self, request, obj, form, change):
        if not change and self.company_field and getattr(obj, f"{self.company_field}_id", None) is None:
            setattr(obj, self.company_field, request.azienda)
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
