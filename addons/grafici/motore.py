"""Il motore di Analisi: i dati di un grafico salvato (dal motore del kernel o dal servizio di previsione), la forma
che Chart.js si aspetta, la cache del proprietario, le schede della dashboard e i widget di una pagina.

Un grafico non è mai un'immagine: è una specifica che si ricalcola, sempre con i permessi di chi guarda. Il
proprietario tiene in cache l'ultima istantanea; chi guarda una pagina condivisa calcola con i propri permessi e
non scrive niente."""
import csv
import datetime
import io

from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core import dashboard as dash
from core import parametri
from core.registry import modules
from core.viste import interroga
from core.viste.interroga import ErroreInterrogazione

from .models import Grafico, Pagina

ICONE = [("bar-chart", "Grafico"), ("pie-chart", "Torta"), ("trending-up", "Tendenza"), ("target", "Obiettivi"),
         ("briefcase", "Lavoro"), ("users", "Persone"), ("calendar", "Calendario"), ("clipboard", "Elenco"),
         ("zap", "Lampo"), ("shield", "Controllo")]
TIPI_SCAMBIABILI = [(t, e) for t, e in Grafico.TIPI if t in Grafico.INTERCAMBIABILI]


def minuti_cache():
    try:
        return int(parametri.leggi("grafici.cache_minuti") or 15)
    except Exception:
        return 15


# ---------- calcolo ----------

def _ai_disponibile():
    return "ai" in settings.ADDONS_ATTIVI and "ai" not in modules.disattivati()


def _previsione(spec, request):
    if not _ai_disponibile():
        raise ErroreInterrogazione("Le previsioni richiedono il modulo Assistente AI con il servizio di previsione.")
    from ai.specialisti import calcola_previsione
    from ai.strumenti import Contesto
    return calcola_previsione(spec, Contesto(utente=request.user, azienda=getattr(request, "azienda", None)))


def dati_di(tipo, spec, request):
    """I dati di una specifica per l'utente della richiesta: {"serie", "totale"} oppure, per le previsioni,
    {"storico", "futuro", "totale", "modello"}."""
    if tipo == Grafico.PREVISIONE:
        return _previsione(spec, request)
    return interroga.calcola(spec, request)


def aggiorna(grafico, request, forza=False):
    """(dati, errore) del grafico: l'istantanea del proprietario se è fresca, altrimenti un ricalcolo, salvato solo
    se chi guarda è il proprietario (gli altri vedono i dati con i propri permessi, senza toccare la cache)."""
    mio = grafico.utente_id == request.user.id
    fresca = grafico.dati and grafico.aggiornato and \
        timezone.now() - grafico.aggiornato < datetime.timedelta(minutes=minuti_cache())
    if mio and fresca and not forza:
        return grafico.dati, ""
    try:
        dati = dati_di(grafico.tipo, grafico.spec, request)
    except ErroreInterrogazione as e:
        return (grafico.dati if mio else {}), str(e)
    if mio:
        grafico.dati, grafico.aggiornato = dati, timezone.now()
        grafico.save(update_fields=["dati", "aggiornato"])
    return dati, ""


def serie_di(grafico, dati):
    """La serie come la disegna core/grafici.js, più le righe per la tabella."""
    if grafico.tipo == Grafico.PREVISIONE:
        storico, futuro = dati.get("storico", []), dati.get("futuro", [])
        return {"tipo": "previsione", "titolo": grafico.titolo, "storico": storico, "futuro": futuro,
                "righe": [(e, v) for e, v in storico], "vuoto": not storico, "totale": dati.get("totale"),
                "modello": dati.get("modello", "")}
    coppie = [tuple(c) for c in dati.get("serie", [])]
    return {"tipo": grafico.tipo if grafico.tipo in Grafico.INTERCAMBIABILI else Grafico.BARRE, "titolo": grafico.titolo,
            "etichette": [e for e, _ in coppie], "valori": [float(v) for _, v in coppie], "righe": coppie,
            "vuoto": not any(v for _, v in coppie), "totale": dati.get("totale")}


def descrizione(spec, request=None):
    """«Somma di totale per mese · Ordini di vendita · 2 filtri»: che cosa calcola la specifica, a parole."""
    vista = None
    if request is not None:
        try:
            vista = interroga.vista_per_nome(spec.get("vista", ""), request)
        except ErroreInterrogazione:
            vista = None
    misura = spec.get("misura", "count") or "count"
    pezzi = []
    if "data" in spec and "orizzonte" in spec:                      # previsione
        pezzi.append(f"previsione a {spec['orizzonte']} {spec.get('per', 'mese')}" + ("i" if spec["orizzonte"] != 1 else ""))
    testo_misura = interroga.etichetta_misura(vista, misura) if vista else misura
    per = spec.get("per", "")
    if per and "orizzonte" not in spec:
        nome, _, parte = per.partition(":")
        etichetta = nome
        if vista:
            try:
                etichetta = str(interroga._percorso(vista, nome, con_operatore=False)[1].verbose_name)
            except ErroreInterrogazione:
                pass
        pezzi.append(f"{testo_misura} per {etichetta.lower()}" + (f" ({parte})" if parte else ""))
    elif "orizzonte" in spec:
        pezzi.append(testo_misura.lower())
    pezzi.append(str(vista.verbose_name_plural) if vista else spec.get("vista", ""))
    filtri = len(spec.get("filtri") or {}) + len([k for k in (spec.get("lista") or {}) if k == "q" or k.startswith("f_")])
    if filtri:
        pezzi.append(f"{filtri} filtr{'o' if filtri == 1 else 'i'}")
    return " · ".join(p for p in pezzi if p)


def widget_salvato(grafico, request, forza=False):
    """Il dizionario che la griglia disegna per un grafico salvato."""
    mio = grafico.utente_id == request.user.id
    dati, errore = aggiorna(grafico, request, forza)
    return {"id": grafico.id_widget, "tipo": "salvato", "titolo": grafico.titolo, "grafico": grafico,
            "serie": serie_di(grafico, dati), "errore": errore, "dom": f"wd-g-{grafico.pk}", "mio": mio,
            "sotto": descrizione(grafico.spec, request), "aggiornato": grafico.aggiornato if mio else timezone.now(),
            "tipi": TIPI_SCAMBIABILI if grafico.tipo in Grafico.INTERCAMBIABILI else []}


def widget_leggero(grafico):
    """Solo il titolo: per il cassetto «Aggiungi widget», senza calcolare niente."""
    return {"id": grafico.id_widget, "tipo": "salvato", "titolo": grafico.titolo, "grafico": grafico, "app": "Libreria",
            "w": 2}


def csv_di(grafico, dati):
    uscita = io.StringIO()
    scrittore = csv.writer(uscita, delimiter=";")
    if grafico.tipo == Grafico.PREVISIONE:
        scrittore.writerow(["Periodo", "Valore", "Previsione 10 %", "Previsione mediana", "Previsione 90 %"])
        scrittore.writerows([[e, v, "", "", ""] for e, v in dati.get("storico", [])])
        scrittore.writerows([[e, "", b, m, a] for e, b, m, a in dati.get("futuro", [])])
    else:
        scrittore.writerow(["Categoria", "Valore"])
        scrittore.writerows(dati.get("serie", []))
    return "﻿" + uscita.getvalue()                            # BOM: Excel legge gli accenti


# ---------- pagine e widget ----------

def catalogo(pagina, request):
    """(widget, libreria): i widget che stanno nella pagina (per la scheda di un'app anche la card dei KPI e i grafici
    del suo manifest) e, se la pagina è di chi guarda, i suoi grafici non ancora in una pagina, da aggiungere."""
    widget = []
    if pagina.app:
        tutti, _ = dash.catalogo(request)
        widget += [w for w in tutti if w["id"].split(":", 1)[0] == pagina.app]
    grafici = list(pagina.grafici.select_related("utente").order_by("pk")) if pagina.pk else []
    widget += [widget_salvato(g, request) for g in grafici]
    libreria = []
    if pagina.utente_id == request.user.id:
        libreria = [widget_leggero(g) for g in Grafico.objects.filter(utente=request.user, pagina__isnull=True)]
    return widget, libreria


def ids_ammessi(pagina, request):
    """Gli id che il layout della pagina può contenere, senza calcolare i dati."""
    ids = set()
    if pagina.app:
        ids |= {w["id"] for w in dash.catalogo(request)[0] if w["id"].split(":", 1)[0] == pagina.app}
    if pagina.pk:
        ids |= {g.id_widget for g in pagina.grafici.all()}
    ids |= {g.id_widget for g in Grafico.objects.filter(utente=request.user, pagina__isnull=True)}
    return ids


def salva_layout(pagina, dati, request):
    """Il layout dal client, validato come quello della dashboard; i grafici della libreria che compaiono nel layout
    entrano nella pagina."""
    layout = dash.layout_valido(dati, [{"id": i} for i in ids_ammessi(pagina, request)])
    citati = {v["id"] for v in layout["widget"]} | set(layout["nascosti"])
    pk_libreria = [int(i[2:]) for i in citati if i.startswith("g:") and i[2:].isdigit()]
    if pk_libreria:
        Grafico.objects.filter(utente=request.user, pagina__isnull=True, pk__in=pk_libreria).update(pagina=pagina)
    pagina.layout = layout
    pagina.save(update_fields=["layout", "aggiornata"])
    return layout


def contesto_ada(pagina, visibili):
    """Che cosa c'è sulla pagina, per chi chiede all'assistente di spiegarla."""
    kpi = [{"app": w["titolo"], "indicatori": [{"etichetta": k["etichetta"], "valore": str(k["valore"])} for k in w["scheda"]["kpi"]]}
           for w in visibili if w["tipo"] == "kpi"]
    grafici = []
    for w in visibili:
        if w["tipo"] == "grafico":
            grafici.append({"app": w["app"], "titolo": w["titolo"], "tipo": w["serie"]["tipo"], "dati": w["serie"]["righe"]})
        elif w["tipo"] == "salvato":
            voce = {"titolo": w["titolo"], "tipo": w["serie"]["tipo"], "query": w["sotto"], "dati": w["serie"]["righe"]}
            if w["serie"].get("futuro"):
                voce["previsione"] = w["serie"]["futuro"]
            grafici.append(voce)
    return {"pagina": f"Analisi: {pagina.titolo}", "kpi": kpi, "grafici": grafici}


# ---------- schede ----------

def _nome(utente):
    return utente.get_full_name() or utente.get_username()


def app_con_indicatori(user):
    """Le app visibili all'utente che hanno una dashboard (KPI o grafici nel manifest)."""
    manifest = modules.manifests_attivi()
    return [a for a in modules.app_visibili(user) if a["slug"] in manifest and manifest[a["slug"]].dashboard]


def schede(request, attiva=""):
    """Le schede della dashboard per chi guarda: le sue pagine libere e quelle condivise con lui, poi una scheda per
    ogni app con indicatori (meno quelle che ha nascosto)."""
    utente = request.user
    pagine = list(Pagina.objects.filter(Q(utente=utente) | Q(condivisa=True)).select_related("utente"))
    voci = []
    libere = sorted([p for p in pagine if not p.app], key=lambda p: (p.utente_id != utente.id, p.ordine, p.pk))
    for p in libere:
        voci.append({"chiave": p.chiave, "titolo": p.titolo, "icona": p.icona, "immagine": "",
                     "url": reverse("grafici:pagina", args=[p.pk]), "condivisa": p.utente_id != utente.id,
                     "proprietario": _nome(p.utente), "attiva": p.chiave == attiva})
    proprie_app = {p.app: p for p in pagine if p.app and p.utente_id == utente.id}
    for app in app_con_indicatori(utente):
        p = proprie_app.get(app["slug"])
        if p and p.nascosta:
            continue
        icona = app.get("icon") or "zap"
        voci.append({"chiave": f"app:{app['slug']}", "titolo": p.titolo if p else app["label"],
                     "icona": "" if "/" in icona else icona, "immagine": icona if "/" in icona else "",
                     "url": reverse("grafici:pagina_app", args=[app["slug"]]), "condivisa": False, "proprietario": "",
                     "attiva": f"app:{app['slug']}" == attiva})
    return voci


def destinazioni(request, vista=""):
    """[(valore, etichetta)] delle pagine in cui si può salvare un grafico: prima la scheda dell'app della vista,
    poi le pagine libere dell'utente, le altre app e «Nuova pagina»."""
    app_vista = (vista or "").split(".", 1)[0]
    apps = app_con_indicatori(request.user)
    scelte = [(f"app:{a['slug']}", f"Scheda {a['label']}") for a in apps if a["slug"] == app_vista]
    scelte += [(str(p.pk), p.titolo) for p in Pagina.objects.filter(utente=request.user, app="")]
    scelte += [(f"app:{a['slug']}", f"Scheda {a['label']}") for a in apps if a["slug"] != app_vista]
    scelte.append(("nuova", "Nuova pagina…"))
    return scelte
