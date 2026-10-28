"""Righe di un documento (one2many di Odoo): formset nel form del padre, tabella in sola lettura nel dettaglio."""
from types import SimpleNamespace

from django.forms import inlineformset_factory, modelform_factory

from . import widgets


class Inline:
    """Righe di `model` collegate al documento dal campo `fk`, con le colonne `fields`.

        inlines = [Inline(RigaVendita, "ordine", ["prodotto", "descrizione", "quantita", "prezzo"], titolo="Righe")]
    """

    def __init__(self, model, fk, fields, titolo=None, extra=1):
        self.model, self.fk, self.fields, self.extra = model, fk, list(fields), extra
        self.titolo = titolo or str(model._meta.verbose_name_plural).capitalize()

    def formset_class(self, documento, azienda_id=None):
        from .base import _campo_form, form_per_azienda
        form = form_per_azienda(modelform_factory(self.model, fields=self.fields, formfield_callback=_campo_form),
                                azienda_id)
        return inlineformset_factory(documento, self.model, form=form, fk_name=self.fk, fields=self.fields,
                                     extra=self.extra, can_delete=True)

    def colonne(self):
        meta = self.model._meta
        return [str(meta.get_field(c).verbose_name).capitalize() for c in self.fields]

    def righe(self, obj, request=None):
        """Valori resi per la tabella del dettaglio (stessa resa delle liste)."""
        finta_vista = SimpleNamespace(opts=self.model._meta)
        return [[widgets.rendi(finta_vista, r, c, request) for c in self.fields]
                for r in self.model._default_manager.filter(**{self.fk: obj}).order_by("pk")]
