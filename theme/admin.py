from django import forms
from django.contrib import admin, messages
from django.contrib.staticfiles import finders
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import LOGO_TIPI, Tema

CSS_MAX = 512 * 1024
LOGO_MAX = 256 * 1024
ESTENSIONI_LOGO = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def css_del_foglio(tema):
    """Il CSS di un tema di sistema, letto dagli statici (per duplicarlo)."""
    trovato = tema.foglio and finders.find(tema.foglio)
    if not trovato:
        return ""
    with open(trovato, encoding="utf-8") as f:
        return f.read()


class TemaForm(forms.ModelForm):
    file_css = forms.FileField(label="Carica un file CSS", required=False,
                               help_text="Sostituisce il CSS qui sotto. Si appoggia al foglio di base: basta ridefinire "
                                         "i token (--ui-primary, --ui-surface…) e le parti da cambiare.")
    file_logo = forms.FileField(label="Logo", required=False,
                                help_text="SVG, PNG, JPG o WebP fino a 256 KB, al posto del cubo nell'header.")
    togli_logo = forms.BooleanField(label="Togli il logo caricato", required=False)

    class Meta:
        model = Tema
        fields = ["nome", "descrizione", "attivo", "colore_barra", "css"]
        widgets = {"css": forms.Textarea(attrs={"rows": 24, "style": "font-family: var(--font-mono); width: 100%;"}),
                   "colore_barra": forms.TextInput(attrs={"placeholder": "#22394a", "size": 9})}

    def clean_file_css(self):
        f = self.cleaned_data.get("file_css")
        if not f:
            return None
        if not f.name.lower().endswith(".css"):
            raise forms.ValidationError("Serve un file .css.")
        if f.size > CSS_MAX:
            raise forms.ValidationError("Il file supera 512 KB.")
        try:
            return f.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise forms.ValidationError("Il file non è in UTF-8.")

    def clean_file_logo(self):
        f = self.cleaned_data.get("file_logo")
        if not f:
            return None
        tipo = ESTENSIONI_LOGO.get("." + f.name.rsplit(".", 1)[-1].lower()) if "." in f.name else None
        if tipo not in LOGO_TIPI:
            raise forms.ValidationError("Il logo dev'essere SVG, PNG, JPG o WebP.")
        if f.size > LOGO_MAX:
            raise forms.ValidationError("Il logo supera 256 KB.")
        dati = f.read()
        if tipo == "image/svg+xml" and b"<svg" not in dati[:2048].lower():
            raise forms.ValidationError("Il file non sembra un SVG.")
        return tipo, dati

    def clean(self):
        dati = super().clean()
        if dati.get("file_css") is not None:
            dati["css"] = dati["file_css"]
        return dati


@admin.register(Tema)
class TemaAdmin(admin.ModelAdmin):
    form = TemaForm
    list_display = ["nome", "stato", "descrizione", "origine", "comandi"]
    list_display_links = ["nome"]
    actions = ["attiva_selezionato", "duplica"]
    readonly_fields = ["foglio_statico", "logo_attuale", "aggiornato"]

    def get_fieldsets(self, request, obj=None):
        fs = [(None, {"fields": ["nome", "descrizione", "attivo", "colore_barra"]}),
              ("Aspetto", {"fields": (["foglio_statico"] if obj and obj.foglio else []) + ["file_css", "css"]}),
              ("Logo", {"fields": (["logo_attuale", "togli_logo"] if obj and obj.logo_tipo else []) + ["file_logo"]})]
        if obj:
            fs.append(("Altro", {"fields": ["aggiornato"]}))
        return fs

    @admin.display(description="Stato")
    def stato(self, obj):
        return mark_safe('<strong style="color: var(--ui-success, #1f7a3a)">● Attivo</strong>') if obj.attivo else "—"

    @admin.display(description="Origine")
    def origine(self, obj):
        return "Di sistema" if obj.di_sistema else "Caricato"

    @admin.display(description="")
    def comandi(self, obj):
        anteprima = reverse("theme:tema_anteprima", args=[obj.pk])
        if obj.attivo:
            return format_html('<a href="{}">Apri</a>', anteprima)
        attiva = reverse("admin:theme_tema_attiva", args=[obj.pk])
        # il bottone invia il form dell'elenco (POST, con il token CSRF) all'indirizzo che attiva il tema
        return format_html('<a href="{}" target="_blank" rel="noopener">Anteprima</a> · '
                           '<button type="submit" formaction="{}" class="button" style="padding: 2px 10px">Attiva</button>', anteprima, attiva)

    @admin.display(description="Foglio statico")
    def foglio_statico(self, obj):
        return format_html("<code>{}</code><br><small>Fa parte dell'applicazione: per cambiarlo usa «Duplica» "
                           "dall'elenco e modifica la copia.</small>", obj.foglio)

    @admin.display(description="Logo attuale")
    def logo_attuale(self, obj):
        url = reverse("theme:tema_logo", args=[obj.pk])
        return format_html('<img src="{}?v={}" alt="" style="max-height: 48px; background: #22394a; padding: 6px; border-radius: 8px;">',
                           url, int(obj.aggiornato.timestamp()))

    def get_urls(self):
        return [path("<int:pk>/attiva/", self.admin_site.admin_view(self.vista_attiva), name="theme_tema_attiva"),
                *super().get_urls()]

    def vista_attiva(self, request, pk):
        if request.method != "POST":
            return redirect("admin:theme_tema_changelist")
        if not self.has_change_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        tema = get_object_or_404(Tema, pk=pk)
        tema.attiva()
        request.session.pop("tema_anteprima", None)
        self.message_user(request, f"Ora tutti vedono il tema «{tema.nome}».", messages.SUCCESS)
        return redirect("admin:theme_tema_changelist")

    def save_model(self, request, obj, form, change):
        logo = form.cleaned_data.get("file_logo")
        if logo:
            obj.logo_tipo, obj.logo = logo
        elif form.cleaned_data.get("togli_logo"):
            obj.logo_tipo, obj.logo = "", None
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and (obj.di_sistema or obj.attivo):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        queryset.filter(di_sistema=False, attivo=False).delete()

    @admin.action(description="Attiva il tema selezionato", permissions=["change"])
    def attiva_selezionato(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Seleziona un solo tema da attivare.", messages.WARNING)
            return
        tema = queryset.get()
        tema.attiva()
        self.message_user(request, f"Ora tutti vedono il tema «{tema.nome}».", messages.SUCCESS)

    @admin.action(description="Duplica (per modificarne una copia)", permissions=["add"])
    def duplica(self, request, queryset):
        with transaction.atomic():
            for tema in queryset:
                nome = f"{tema.nome} (copia)"
                n = 2
                while Tema.objects.filter(nome=nome).exists():
                    nome, n = f"{tema.nome} (copia {n})", n + 1
                css = "\n\n".join(c for c in (css_del_foglio(tema), tema.css) if c.strip())
                Tema.objects.create(nome=nome, descrizione=tema.descrizione, css=css, colore_barra=tema.colore_barra,
                                    logo=tema.logo, logo_tipo=tema.logo_tipo)
        self.message_user(request, "Copia creata: aprila per cambiare colori e logo.", messages.SUCCESS)
