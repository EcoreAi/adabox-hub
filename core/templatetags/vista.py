from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def querystring_con(context, **kwargs):
    """Query string corrente con i parametri dati sostituiti (None li toglie). Inizia con '?'."""
    query = context["request"].GET.copy()
    for chiave, valore in kwargs.items():
        if valore is None:
            query.pop(chiave, None)
        else:
            query[chiave] = valore
    query.pop("partial", None)
    return "?" + query.urlencode() if query else "?"


@register.simple_tag(takes_context=True)
def cella(context, vista, obj, campo):
    return vista.col_valore(context["request"], obj, campo)


CLASSI_WIDGET = {
    "CheckboxInput": "ui-checkbox",
    "Select": "ui-input ui-select", "SelectMultiple": "ui-input ui-select", "NullBooleanSelect": "ui-input ui-select",
    "Textarea": "ui-input ui-textarea",
    "ClearableFileInput": "ui-file", "FileInput": "ui-file",
    "CheckboxSelectMultiple": "ui-checkbox-list", "RadioSelect": "ui-checkbox-list",
}


@register.filter
def con_classe(campo):
    """Il widget del BoundField con la classe del theme adatta al tipo."""
    widget = campo.field.widget
    classe = CLASSI_WIDGET.get(type(widget).__name__, "ui-input")
    attrs = {"class": f"{widget.attrs.get('class', '')} {classe}".strip()}
    if campo.errors:
        attrs["aria-invalid"] = "true"
    return campo.as_widget(attrs=attrs)


@register.filter
def e_checkbox(campo):
    return type(campo.field.widget).__name__ == "CheckboxInput"


@register.inclusion_tag("core/vista/_campo.html")
def campo(bound_field):
    return {"campo": bound_field}
