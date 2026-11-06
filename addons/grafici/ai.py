"""Strumenti dell'assistente per Analisi (chiave "ai" del manifest): leggere le pagine e i loro numeri, salvare un
grafico o un KPI in una pagina (anche quello appena disegnato in chat), creare una pagina. Le scritture passano
dall'anteprima e dalla conferma dell'utente come tutte le altre; i numeri li calcola sempre il database."""
from django.db.models import Q
from django.urls import reverse

from ai.strumenti import ErroreStrumento, Strumento, registra, richiesta
from ai.strumenti.viste import FILTRI, TESTO, VISTA
from core import dashboard as dash
from core.viste.interroga import ErroreInterrogazione

from . import motore
from .models import Grafico, Pagina

TIPI = [t for t, _ in Grafico.TIPI]


def _url(p):
    return reverse("grafici:pagina_app", args=[p.app]) if p.app else reverse("grafici:pagina", args=[p.pk])


def _mie_e_condivise(contesto):
    return ((Pagina.objects.filter(utente=contesto.utente) | motore.condivise(contesto.azienda)).distinct()
            .select_related("utente").order_by("app", "ordine", "pk"))


def _trova(contesto, pagina):
    """Una pagina per id o titolo, tra quelle che l'utente vede."""
    testo = str(pagina or "").strip()
    qs = _mie_e_condivise(contesto)
    p = qs.filter(pk=int(testo)).first() if testo.isdigit() else qs.filter(titolo__iexact=testo).first()
    if p is None:
        raise ErroreStrumento(f"Nessuna pagina «{pagina}»: usa analisi_pagine per l'elenco.")
    return p


def analisi_pagine(contesto):
    voci = [{"id": p.pk, "titolo": p.titolo, "app": p.app, "mia": p.utente_id == contesto.utente.id,
             "condivisa": p.condivisa, "widget": p.n_widget, "url": _url(p)} for p in _mie_e_condivise(contesto)]
    return voci or "Nessuna pagina di Analisi: se ne può creare una con analisi_crea_pagina."


def analisi_leggi_pagina(contesto, pagina):
    p = _trova(contesto, pagina)
    request = richiesta.per(contesto)
    widget, _ = motore.catalogo(p, request)
    visibili, _ = dash.disponi(p.layout, widget)
    return {**motore.contesto_ada(p, visibili), "url": _url(p),
            "nota": "Numeri calcolati adesso con i permessi dell'utente; i grafici con «query» sono salvati nella pagina."}


def _specifica(contesto, titolo, vista, tipo, misura, per, data, periodo, orizzonte, filtri, testo, artifact):
    """(tipo, spec, titolo) da controllare: dall'artifact già in chat oppure dai campi."""
    if artifact:
        from ai.models import Artifact
        a = Artifact.objects.filter(pk=artifact, utente=contesto.utente, tipo=Artifact.GRAFICO).first()
        if a is None:
            raise ErroreStrumento(f"Nessun grafico n. {artifact} in questa chat.")
        tipo_a = a.spec.get("grafico", Grafico.BARRE)
        return (tipo_a if tipo_a in TIPI else Grafico.BARRE,
                {k: v for k, v in a.spec.items() if k not in ("tipo", "grafico")}, titolo or a.titolo)
    if not vista:
        raise ErroreStrumento("Indica «vista» (o «artifact» per salvare un grafico già disegnato).")
    if tipo not in TIPI:
        raise ErroreStrumento(f"«tipo» è uno tra: {', '.join(TIPI)}.")
    spec = {"vista": vista, "misura": misura or "count"}
    if tipo == Grafico.KPI:
        if data:
            spec["data"], spec["periodo"] = data, periodo or "mese"
    elif tipo == Grafico.PREVISIONE:
        if not data:
            raise ErroreStrumento("Una previsione ha bisogno del campo «data».")
        if (periodo or "mese") not in ("mese", "settimana", "giorno"):
            raise ErroreStrumento("Per una previsione «periodo» è mese, settimana o giorno.")
        spec["data"], spec["per"], spec["orizzonte"] = data, periodo or "mese", max(1, min(int(orizzonte or 3), 24))
    else:
        if not per:
            raise ErroreStrumento("Un grafico ha bisogno di «per» (campo o data:mese…).")
        spec["per"] = per
    if filtri:
        spec["filtri"] = filtri
    if testo:
        spec["testo"] = testo
    return tipo, spec, titolo


def _controlla(contesto, tipo, spec):
    request = richiesta.per(contesto)
    vista = motore.vista_di(spec, request)
    if vista is None:
        raise ErroreStrumento(f"Vista «{spec.get('vista')}» inesistente o non accessibile.")
    try:
        dati = motore.dati_di(tipo, spec, request)
    except ErroreInterrogazione as e:
        raise ErroreStrumento(str(e))
    return vista, dati


def _dove(contesto, pagina):
    """Che pagina sarà, a parole, senza crearla."""
    testo = str(pagina or "").strip()
    if not testo:
        return "libreria (nessuna pagina)"
    if testo.startswith("app:"):
        return f"scheda dell'app «{testo[4:]}»"
    if Pagina.objects.filter(utente=contesto.utente).filter(Q(titolo__iexact=testo) | (Q(pk=int(testo)) if testo.isdigit() else Q())).exists():
        return f"pagina «{testo}»"
    return f"pagina nuova «{testo}»"


def anteprima_salva(contesto, titolo="", vista="", tipo="barre", misura="count", per="", data="", periodo="mese",
                    orizzonte=3, filtri=None, testo="", pagina="", artifact=None, obiettivo=None):
    tipo, spec, titolo = _specifica(contesto, titolo, vista, tipo, misura, per, data, periodo, orizzonte, filtri, testo, artifact)
    vista_obj, _ = _controlla(contesto, tipo, spec)
    descrizione = motore.descrizione(spec, vista=vista_obj, tipo=tipo)
    titolo = (titolo or descrizione)[:200]
    return {"titolo": f"Salva {'il KPI' if tipo == Grafico.KPI else 'il grafico'} «{titolo}» in Analisi",
            "dettagli": [{"campo": "Query", "dopo": descrizione}, {"campo": "Tipo", "dopo": dict(Grafico.TIPI)[tipo]},
                         *([{"campo": "Obiettivo", "dopo": str(obiettivo)}] if obiettivo else []),
                         {"campo": "Dove", "dopo": _dove(contesto, pagina)}]}


def salva_grafico(contesto, titolo="", vista="", tipo="barre", misura="count", per="", data="", periodo="mese",
                  orizzonte=3, filtri=None, testo="", pagina="", artifact=None, obiettivo=None):
    tipo, spec, titolo = _specifica(contesto, titolo, vista, tipo, misura, per, data, periodo, orizzonte, filtri, testo, artifact)
    vista_obj, dati = _controlla(contesto, tipo, spec)
    testo_pagina = str(pagina or "").strip()
    try:
        p = motore.destinazione(contesto.utente, testo_pagina)
    except ValueError:
        p = motore.nuova_pagina(contesto.utente, testo_pagina) if not testo_pagina.startswith("app:") else None
        if p is None:
            raise ErroreStrumento(f"Nessuna scheda dell'app «{testo_pagina[4:]}».")
    from django.utils import timezone
    g = Grafico.objects.create(
        utente=contesto.utente, titolo=(titolo or motore.descrizione(spec, vista=vista_obj, tipo=tipo))[:200],
        tipo=tipo, spec=spec, dati=dati, aggiornato=timezone.now(), origine=Grafico.CHAT,
        opzioni={"obiettivo": float(obiettivo)} if obiettivo else {},
        origine_url=reverse("ai:conversazione", args=[contesto.conversazione_id]) if getattr(contesto, "conversazione_id", None)
        else (reverse("ai:conversazione", args=[contesto.conversazione.pk]) if contesto.conversazione else ""))
    if p is not None:
        motore.metti_in_pagina(p, g)
    url = _url(p) if p else reverse("grafici:grafico", args=[g.pk])
    return {"esito": f"Salvato «{g.titolo}»" + (f" nella pagina «{p.titolo}»." if p else " in libreria."), "url": url, "grafico": g.pk}


def anteprima_crea_pagina(contesto, titolo, icona="bar-chart"):
    titolo = (titolo or "").strip()
    if not titolo:
        raise ErroreStrumento("Serve un titolo.")
    if Pagina.objects.filter(utente=contesto.utente, titolo__iexact=titolo).exists():
        raise ErroreStrumento(f"La pagina «{titolo}» esiste già.")
    return {"titolo": f"Crea la pagina di Analisi «{titolo}»",
            "dettagli": [{"campo": "Icona", "dopo": dict(motore.ICONE).get(icona, "Grafico")},
                         {"campo": "Dove", "dopo": "una scheda nuova sulla dashboard, in coda alle tue"}]}


def crea_pagina(contesto, titolo, icona="bar-chart"):
    p = motore.nuova_pagina(contesto.utente, titolo, icona)
    return {"esito": f"Pagina «{p.titolo}» creata.", "url": _url(p), "pagina": p.pk}


registra(Strumento(
    "analisi_pagine", "Le pagine di Analisi dell'utente (le schede della sua dashboard) e quelle condivise con lui, "
                      "con quanti widget hanno.",
    {"type": "object", "properties": {}, "required": []}, analisi_pagine, permesso="grafici.view_pagina"))
registra(Strumento(
    "analisi_leggi_pagina", "I numeri di una pagina di Analisi adesso: KPI, grafici salvati con la loro query e i "
                            "dati, previsioni. Per commentare o riassumere una pagina, anche nelle attività pianificate.",
    {"type": "object", "properties": {"pagina": {"type": "string", "description": "titolo o id della pagina"}},
     "required": ["pagina"]}, analisi_leggi_pagina, permesso="grafici.view_pagina"))
registra(Strumento(
    "analisi_salva_grafico", "Salva in una pagina di Analisi un grafico, un KPI o una previsione che si ricalcolano "
                             "da soli: passa «artifact» per salvare il grafico appena disegnato in chat, oppure la "
                             "query (vista, misura, per o data). Si propone all'utente, che conferma.",
    {"type": "object", "properties": {
        "titolo": {"type": "string"}, "vista": VISTA,
        "tipo": {"type": "string", "enum": TIPI, "description": "barre (default), barre_orizzontali, linee, area, torta, "
                                                                 "kpi (numero con variazione sul periodo prima), previsione"},
        "misura": {"type": "string", "description": "count (default) oppure sum:campo, avg:campo"},
        "per": {"type": "string", "description": "raggruppamento per i grafici: campo o data:mese, data:anno…"},
        "data": {"type": "string", "description": "campo data per kpi (periodo in corso) e previsione (serie storica)"},
        "periodo": {"type": "string", "enum": ["giorno", "settimana", "mese", "anno"], "description": "per kpi e previsione (default mese)"},
        "orizzonte": {"type": "integer", "description": "periodi da prevedere (1-24, default 3)"},
        "filtri": FILTRI, "testo": TESTO,
        "pagina": {"type": "string", "description": "titolo di una pagina dell'utente (se non esiste viene creata), oppure "
                                                    "app:slug per la scheda di un'app; vuoto = libreria"},
        "artifact": {"type": "integer", "description": "id del grafico già disegnato in chat: ne copia la query"},
        "obiettivo": {"type": "number", "description": "valore obiettivo: una linea sul grafico, la barra di avanzamento sul KPI"}},
     "required": []}, salva_grafico, rischio="scrittura", concorrente=False, anteprima=anteprima_salva,
    permesso="grafici.add_grafico"))
registra(Strumento(
    "analisi_crea_pagina", "Crea una pagina di Analisi vuota (una scheda nuova sulla dashboard). Si propone all'utente, che conferma.",
    {"type": "object", "properties": {"titolo": {"type": "string"},
                                      "icona": {"type": "string", "enum": [i for i, _ in motore.ICONE]}},
     "required": ["titolo"]}, crea_pagina, rischio="scrittura", concorrente=False, anteprima=anteprima_crea_pagina,
    permesso="grafici.add_pagina"))
