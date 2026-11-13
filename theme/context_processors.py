from django.conf import settings

DEFAULTS = {
    "brand": "Progetto",
    "mark": "PR",
    "company": "",
    "company_url": "",
    "version": "",
    "nav": [],
    "theme_color": "#1e3a8a",   # barra del browser sul telefono e manifest dell'app installata
}

SESSIONE_ANTEPRIMA = "tema_anteprima"


def tema_corrente(request=None):
    """Il tema da mostrare: quello in anteprima per lo staff che l'ha chiesta, altrimenti quello attivo.
    None se non ce n'è uno o se la tabella non c'è ancora (prima delle migrazioni)."""
    from .models import Tema
    campi = ("pk", "nome", "foglio", "css", "colore_barra", "logo_tipo", "aggiornato", "attivo")
    try:
        anteprima = request is not None and getattr(request, "session", None) is not None \
            and request.user.is_authenticated and request.user.is_staff and request.session.get(SESSIONE_ANTEPRIMA)
        if anteprima:
            tema = Tema.objects.filter(pk=anteprima).only(*campi[1:]).first()
            if tema:
                return tema
        return Tema.objects.filter(attivo=True).only(*campi[1:]).first()
    except Exception:            # tabella mancante, database non raggiungibile (o vietato, nei test senza db): aspetto di base
        return None


def descrivi(tema):
    """Quello che serve ai template, senza il CSS (che si scarica a parte)."""
    if tema is None:
        return None
    from django.urls import reverse

    from .templatetags.tema import statico
    fogli = [statico(tema.foglio)] if tema.foglio else []
    versione = int(tema.aggiornato.timestamp()) if tema.aggiornato else 0
    if tema.css.strip():
        fogli.append(f"{reverse('theme:tema_css', args=[tema.pk])}?v={versione}")
    return {"pk": tema.pk, "nome": tema.nome, "fogli": fogli, "anteprima": not tema.attivo,
            "logo_url": f"{reverse('theme:tema_logo', args=[tema.pk])}?v={versione}" if tema.logo_tipo else "",
            "colore_barra": tema.colore_barra}


def theme(request):
    """Espone `theme` ai template: default + settings.THEME, più il tema grafico scelto dall'admin (`theme.tema`)."""
    dati = {**DEFAULTS, **getattr(settings, "THEME", {})}
    if request is not None and hasattr(request, "_tema_grafico"):        # core.context_processors lo richiama
        tema = request._tema_grafico
    else:
        tema = descrivi(tema_corrente(request))
        if request is not None:
            request._tema_grafico = tema
    if tema:
        dati["tema"] = tema
        if tema["colore_barra"]:
            dati["theme_color"] = tema["colore_barra"]
    return {"theme": dati}
