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
    """Il tema da mostrare: quello in anteprima per lo staff che l'ha chiesta; nelle pagine pubbliche quello
    dell'azienda del documento (theme.per_azienda); quello dell'azienda corrente; altrimenti quello attivo.
    None se non ce n'è uno o se la tabella non c'è ancora (prima delle migrazioni)."""
    from .models import Tema
    campi = ("pk", "nome", "foglio", "css", "colore_barra", "logo_tipo", "aggiornato", "attivo", "marchio", "template")
    try:
        anteprima = request is not None and getattr(request, "session", None) is not None \
            and request.user.is_authenticated and request.user.is_staff and request.session.get(SESSIONE_ANTEPRIMA)
        if anteprima:
            tema = Tema.objects.filter(pk=anteprima).only(*campi[1:]).first()
            if tema:
                return tema
        azienda = request is not None and (getattr(request, "azienda_tema", None) or getattr(request, "azienda", None))
        if azienda and getattr(azienda, "tema_id", None):
            tema = Tema.objects.filter(pk=azienda.tema_id).only(*campi[1:]).first()
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
    return {"pk": tema.pk, "nome": tema.nome, "fogli": fogli, "anteprima": not tema.attivo, "versione": versione,
            "logo_url": f"{reverse('theme:tema_logo', args=[tema.pk])}?v={versione}" if tema.logo_tipo else "",
            "colore_barra": tema.colore_barra, "marchio": tema.marchio, "template": tema.template}


def tema_della_richiesta(request):
    """Il tema descritto per la richiesta, calcolato una volta (lo usano il context processor e il loader dei template
    del tema)."""
    if request is None:
        return descrivi(tema_corrente(None))
    if not hasattr(request, "_tema_grafico"):
        request._tema_grafico = descrivi(tema_corrente(request))
    return request._tema_grafico


def theme(request):
    """Espone `theme` ai template: default + settings.THEME, più il tema grafico scelto dall'admin (`theme.tema`)."""
    dati = {**DEFAULTS, **getattr(settings, "THEME", {})}
    tema = tema_della_richiesta(request)                 # una volta per richiesta: core.context_processors lo richiama
    if tema:
        dati["tema"] = tema
        if tema["colore_barra"]:
            dati["theme_color"] = tema["colore_barra"]
        if tema["marchio"]:
            dati["brand"] = tema["marchio"]
    return {"theme": dati}
