"""Dashboard: KPI e grafici forniti dalle app installate (chiave `dashboard` del manifest), disposti come widget
che ogni utente ordina, allarga, toglie e rimette.

La funzione di un'app riceve la richiesta e restituisce
    {"kpi": [{"valore": 4, "etichetta": "da fare", "url": "/todo/attivita/?f_stato=aperta"}, ...],
     "grafici": [{"titolo": "...", "tipo": "barre|linee|torta", "dati": [(etichetta, valore), ...], "url": "..."}]}
Il primo KPI è il numero grande della card; i conteggi vanno fatti con `queryset(request, Modello)`, che applica
azienda corrente, visibilità e permessi della ModelView del modello.
"""
import logging

from django.utils.safestring import mark_safe

from .models import DashboardUtente

from . import attivita, svg
from .lavori import risolvi
from .registry import modules

log = logging.getLogger("core.dashboard")


def queryset(request, modello):
    """Record del modello che l'utente vede (stesse regole della lista); vuoto senza permesso di vista."""
    from .viste import registry
    vista = registry.per_modello(modello)
    if vista is None or not vista.has_view_permission(request):
        return modello._default_manager.none()
    return vista.get_queryset(request)


def numero(valore):
    from .viste.gruppi import numero as formatta
    return formatta(valore)


def schede(request):
    """[{slug, label, icon, url, kpi, grafici}] per le app visibili all'utente che dichiarano una dashboard."""
    manifest = modules.manifests_attivi()
    risultato = []
    for app in modules.app_visibili(request.user):
        funzione = manifest[app["slug"]].dashboard if app["slug"] in manifest else None
        if not funzione:
            continue
        try:
            dati = risolvi(funzione)(request) or {}
        except Exception:                      # una app con un errore non deve rompere la dashboard
            log.exception("dashboard di %s non disponibile", app["slug"])
            continue
        risultato.append({**app, "kpi": dati.get("kpi", []), "grafici": dati.get("grafici", [])})
    return risultato


def scheda_attivita(request):
    """Card del kernel: le attività pianificate dell'utente."""
    mie = attivita.mie(request.user)
    totale = mie.count()
    if not totale:
        return None
    from django.urls import reverse
    return {"slug": "attivita", "label": "Le mie attività", "icon": "check", "url": reverse("core:attivita"),
            "kpi": [{"valore": attivita.da_fare_oggi(request.user), "etichetta": "oggi o scadute"},
                    {"valore": totale, "etichetta": "in tutto"}], "grafici": []}


def grafici(schede_app):
    """I grafici di tutte le app, già disegnati in SVG."""
    disegnati = []
    for scheda in schede_app:
        for g in scheda["grafici"]:
            dati = [(e, v) for e, v in g.get("dati", []) if v is not None]
            disegnati.append({"titolo": g["titolo"], "app": scheda["label"], "url": g.get("url") or scheda["url"],
                              "svg": mark_safe(svg.DISEGNI.get(g.get("tipo", "barre"), svg.barre)(dati, g["titolo"]))
                              if any(v for _, v in dati) else None})
    return disegnati


# ---------- widget

LARGHEZZE = (1, 2, 3, 4)
LARGHEZZA_PREDEFINITA = {"kpi": 1, "grafico": 2}
MAX_WIDGET = 200


def _serie(g):
    """I dati di un grafico come li disegna il client (Chart.js), più le righe per la tabella."""
    dati = [(str(e), float(v)) for e, v in g.get("dati", []) if v is not None]
    return {"tipo": g.get("tipo", "barre"), "titolo": g["titolo"], "etichette": [e for e, _ in dati], "valori": [v for _, v in dati],
            "righe": dati, "vuoto": not any(v for _, v in dati)}


def catalogo(request, extra=True):
    """(widget, schede): tutti i widget che l'utente può mettere in dashboard, cioè la card con i KPI e i grafici di ogni app
    che vede, più «Le mie attività». Gli id restano stabili tra una visita e l'altra: «todo:kpi», «vendite:g0»."""
    schede_app = schede(request)
    widget = []
    attivita_kernel = scheda_attivita(request)
    if attivita_kernel:
        widget.append({"id": "core:attivita", "tipo": "kpi", "titolo": attivita_kernel["label"], "scheda": attivita_kernel})
    for s in schede_app:
        widget.append({"id": f"{s['slug']}:kpi", "tipo": "kpi", "titolo": s["label"], "scheda": s})
        for i, g in enumerate(s["grafici"]):
            widget.append({"id": f"{s['slug']}:g{i}", "tipo": "grafico", "titolo": g["titolo"], "app": s["label"],
                           "url": g.get("url") or s["url"], "serie": _serie(g), "dom": f"wd-serie-{s['slug']}-{i}"})
    if extra:
        from .registry import hooks
        for funzione in hooks.widget_extra(request):
            try:
                widget += risolvi(funzione)(request)
            except Exception:                  # un modulo con un errore non deve rompere la dashboard
                log.exception("widget di %s non disponibili", funzione)
    return widget, ([attivita_kernel] if attivita_kernel else []) + schede_app


def carica(visibili):
    """I widget in vista, completi: quelli dei moduli calcolano i dati solo qui, non per stare in libreria."""
    return [{**w, **w["carica"]()} if w.get("carica") else w for w in visibili]


def layout_di(utente):
    return DashboardUtente.objects.filter(utente=utente).values_list("layout", flat=True).first() or {}


def disponi(layout, widget):
    """(visibili, nascosti) nell'ordine e con la larghezza di `layout` ({"widget": [{"id", "w"}], "nascosti": [id]});
    i widget nuovi vanno in coda, quelli tolti a parte. Quelli `su_richiesta` compaiono solo se messi nel layout."""
    per_id = {w["id"]: w for w in widget}
    visibili = []
    for voce in (layout or {}).get("widget", []):
        w = per_id.pop(voce.get("id"), None) if isinstance(voce, dict) else None
        if w:
            w["w"] = voce.get("w") if voce.get("w") in LARGHEZZE else w.get("larghezza") or LARGHEZZA_PREDEFINITA.get(w["tipo"], 2)
            visibili.append(w)
    da_nascondere = set((layout or {}).get("nascosti", []))
    nascosti = []
    for w in widget:
        if w["id"] in per_id:
            w["w"] = w.get("larghezza") or LARGHEZZA_PREDEFINITA.get(w["tipo"], 2)
            (nascosti if w["id"] in da_nascondere or w.get("su_richiesta") else visibili).append(w)
    return visibili, nascosti


def disposizione(utente, widget):
    """La dashboard dell'utente: disponi() con il layout che ha salvato."""
    return disponi(layout_di(utente), widget)


def layout_valido(dati, widget):
    """Dal client: {"widget": [{"id", "w"}], "nascosti": [id]}. Passano solo gli id del catalogo e le larghezze ammesse."""
    if not isinstance(dati, dict):
        raise ValueError("formato non valido")
    ammessi = {w["id"] for w in widget}
    visti, voci = set(), []
    for v in list(dati.get("widget") or [])[:MAX_WIDGET]:
        if isinstance(v, dict) and v.get("id") in ammessi and v["id"] not in visti:
            visti.add(v["id"])
            voci.append({"id": v["id"], "w": v["w"]} if v.get("w") in LARGHEZZE else {"id": v["id"]})
    nascosti = [i for i in list(dati.get("nascosti") or [])[:MAX_WIDGET] if isinstance(i, str) and i in ammessi and i not in visti]
    return {"widget": voci, "nascosti": sorted(set(nascosti))}


def salva_layout(utente, dati, widget):
    layout = layout_valido(dati, widget)
    DashboardUtente.objects.update_or_create(utente=utente, defaults={"layout": layout})
    return layout


def contesto_per_ada(visibili):
    """Che cosa c'è sulla dashboard, per chi chiede all'assistente di spiegarla."""
    kpi = [{"app": w["titolo"], "indicatori": [{"etichetta": k["etichetta"], "valore": str(k["valore"])} for k in w["scheda"]["kpi"]]}
           for w in visibili if w["tipo"] == "kpi"]
    grafici = [{"app": w["app"], "titolo": w["titolo"], "tipo": w["serie"]["tipo"], "dati": w["serie"]["righe"]} for w in visibili if w["tipo"] == "grafico"]
    grafici += [{"titolo": w["titolo"], "tipo": w["serie"]["tipo"], "dati": w["serie"].get("righe", [])} for w in visibili if w["tipo"] == "salvato"]
    return {"pagina": "Dashboard", "kpi": kpi, "grafici": grafici}
