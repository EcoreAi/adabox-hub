"""Il motore di Analisi: i dati di un grafico salvato (dal motore del kernel o dal servizio di previsione), la forma
che Chart.js si aspetta, la cache del proprietario, le schede della dashboard e i widget di una pagina.

Un grafico non è mai un'immagine: è una specifica che si ricalcola, sempre con i permessi di chi guarda. Il
proprietario tiene in cache l'ultima istantanea; chi guarda una pagina condivisa calcola con i propri permessi e
non scrive niente."""
import csv
import datetime
import io
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core import dashboard as dash
from core import parametri
from core.registry import modules
from core.viste import interroga
from core.viste.gruppi import numero
from core.viste.interroga import ErroreInterrogazione

from .models import Grafico, Pagina

ICONE = [("bar-chart", "Grafico"), ("pie-chart", "Torta"), ("trending-up", "Tendenza"), ("target", "Obiettivi"),
         ("briefcase", "Lavoro"), ("users", "Persone"), ("calendar", "Calendario"), ("clipboard", "Elenco"),
         ("zap", "Lampo"), ("shield", "Controllo")]
TIPI_SCAMBIABILI = [(t, e) for t, e in Grafico.TIPI if t in Grafico.INTERCAMBIABILI]
AGGIORNAMENTI = [(0, "Mai: solo a mano"), (1, "Ogni ora"), (6, "Ogni 6 ore"), (24, "Ogni giorno"), (168, "Ogni settimana")]


def minuti_cache():
    try:
        return int(parametri.leggi("grafici.cache_minuti") or 15)
    except Exception:
        return 15


# ---------- calcolo ----------

def _ai_disponibile():
    return "ai" in settings.ADDONS_ATTIVI and "ai" not in modules.disattivati()


def previsioni_disponibili():
    """Il servizio di previsione c'è: modulo AI attivo e indirizzo configurato."""
    if not _ai_disponibile():
        return False
    from ai import specialisti
    return bool(specialisti.url("url_forecast"))


def _previsione(spec, request):
    if not _ai_disponibile():
        raise ErroreInterrogazione("Le previsioni richiedono il modulo Assistente AI con il servizio di previsione.")
    from ai.specialisti import calcola_previsione
    from ai.strumenti import Contesto
    return calcola_previsione(spec, Contesto(utente=request.user, azienda=getattr(request, "azienda", None)))


def dati_di(tipo, spec, request):
    """I dati di una specifica per l'utente della richiesta: {"serie", "chiavi", "totale"}, per i KPI {"valore",
    "precedente", "delta", "storico"}, per le previsioni {"storico", "futuro", "totale", "modello"}."""
    if tipo == Grafico.PREVISIONE:
        return _previsione(spec, request)
    if tipo == Grafico.KPI:
        return interroga.kpi(spec, request)
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


def vista_di(spec, request):
    """La ModelView della specifica, se chi guarda può vederla; altrimenti None."""
    try:
        return interroga.vista_per_nome(spec.get("vista", ""), request)
    except ErroreInterrogazione:
        return None


def link_lista(vista, spec, chiave):
    """L'indirizzo della lista filtrata sul gruppo con quella chiave (drill-down), o None se il campo del
    raggruppamento non è tra i filtri della lista: un link che non filtra sarebbe una bugia."""
    per = spec.get("per", "") or ""
    nome, _, parte = per.partition(":")
    if vista is None or chiave is None or nome not in vista.list_filter:
        return None
    parametri_lista = dict(spec.get("lista") or {})
    for k, v in (spec.get("filtri") or {}).items():          # i filtri semplici dell'assistente su campi della lista
        if "__" not in k and k in vista.list_filter and not isinstance(v, (list, dict)):
            parametri_lista[f"f_{k}"] = v
    if parte:
        try:
            inizio = datetime.date.fromisoformat(str(chiave))
        except ValueError:
            return None
        fine = interroga.avanti_periodo(inizio, parte) - datetime.timedelta(days=1)
        parametri_lista[f"f_{nome}_da"], parametri_lista[f"f_{nome}_a"] = inizio.isoformat(), fine.isoformat()
    else:
        parametri_lista[f"f_{nome}"] = "1" if chiave is True else "0" if chiave is False else str(chiave)
    try:
        return vista.url("lista") + "?" + urlencode(parametri_lista)
    except Exception:
        return None


def testo_valore(valore, unita=""):
    """«12.500,00 €», «7»: il numero come lo legge un italiano."""
    if valore is None:
        return "—"
    if isinstance(valore, float) and valore.is_integer() and not unita:
        valore = int(valore)
    return numero(valore) + (f" {unita}" if unita else "")


def serie_di(grafico, dati, vista=None):
    """La serie come la disegna core/grafici.js, più le righe per la tabella e i link del drill-down."""
    if grafico.tipo == Grafico.PREVISIONE:
        storico, futuro = dati.get("storico", []), dati.get("futuro", [])
        return {"tipo": "previsione", "titolo": grafico.titolo, "storico": storico, "futuro": futuro,
                "righe": [(e, v) for e, v in storico], "vuoto": not storico, "totale": dati.get("totale"),
                "modello": dati.get("modello", "")}
    if grafico.tipo == Grafico.KPI:
        storico = [tuple(c) for c in dati.get("storico", [])]
        delta = dati.get("delta")
        nomi = interroga.NOMI_PERIODO.get(dati.get("periodo", ""), ("", ""))
        return {"tipo": "kpi", "titolo": grafico.titolo, "valore": dati.get("valore"), "unita": dati.get("unita", ""),
                "valore_testo": testo_valore(dati.get("valore"), dati.get("unita", "")), "delta": delta,
                "delta_testo": (f"{'+' if delta > 0 else ''}{testo_valore(delta)} %" if delta is not None else ""),
                "precedente_testo": testo_valore(dati.get("precedente"), dati.get("unita", "")) if dati.get("precedente") is not None else "",
                "periodo_testo": f"{nomi[0]} · {nomi[1]}: {testo_valore(dati.get('precedente'), dati.get('unita', ''))}" if dati.get("periodo") else "in tutto",
                "etichette": [e for e, _ in storico], "valori": [float(v) for _, v in storico], "righe": storico,
                "vuoto": dati.get("valore") is None}
    coppie = [tuple(c) for c in dati.get("serie", [])]
    chiavi = dati.get("chiavi") or [None] * len(coppie)
    link = [link_lista(vista, grafico.spec, k) for k in chiavi] if vista is not None else []
    return {"tipo": grafico.tipo if grafico.tipo in Grafico.INTERCAMBIABILI else Grafico.BARRE, "titolo": grafico.titolo,
            "etichette": [e for e, _ in coppie], "valori": [float(v) for _, v in coppie], "righe": coppie,
            "vuoto": not any(v for _, v in coppie), "totale": dati.get("totale"),
            "link": link if any(link) else []}


def descrizione(spec, request=None, vista=None, tipo=""):
    """«Somma di totale per mese · Ordini di vendita · 2 filtri»: che cosa calcola la specifica, a parole."""
    if vista is None and request is not None:
        vista = vista_di(spec, request)
    misura = spec.get("misura", "count") or "count"
    testo_misura = interroga.etichetta_misura(vista, misura) if vista else misura

    def nome_campo(nome):
        if vista:
            try:
                return str(interroga._percorso(vista, nome, con_operatore=False)[1].verbose_name)
            except ErroreInterrogazione:
                pass
        return nome
    pezzi = []
    if tipo == Grafico.KPI or ("data" in spec and "per" not in spec and "orizzonte" not in spec):
        if spec.get("data"):
            nomi = interroga.NOMI_PERIODO.get(spec.get("periodo", "mese"), ("nel periodo", "prima"))
            pezzi.append(f"{testo_misura} {nomi[0]} (per {nome_campo(spec['data']).lower()}) rispetto a {nomi[1]}")
        else:
            pezzi.append(f"{testo_misura} in tutto")
    elif "orizzonte" in spec:
        n, unita = spec["orizzonte"], spec.get("per", "mese")
        plurali = {"mese": "mesi", "settimana": "settimane", "giorno": "giorni"}
        pezzi.append(f"previsione di {testo_misura.lower()} a {n} {plurali.get(unita, unita) if n != 1 else unita}")
    else:
        per = spec.get("per", "") or ""
        nome, _, parte = per.partition(":")
        if per:
            pezzi.append(f"{testo_misura} per {nome_campo(nome).lower()}" + (f" ({parte})" if parte else ""))
    pezzi.append(str(vista.verbose_name_plural) if vista else spec.get("vista", ""))
    filtri = len(spec.get("filtri") or {}) + len([k for k, v in (spec.get("lista") or {}).items() if (k == "q" or k.startswith("f_")) and v != ""])
    if filtri:
        pezzi.append(f"{filtri} filtr{'o' if filtri == 1 else 'i'}")
    return " · ".join(p for p in pezzi if p)


def widget_salvato(grafico, request, forza=False):
    """Il dizionario che la griglia disegna per un grafico salvato."""
    mio = grafico.utente_id == request.user.id
    vista = vista_di(grafico.spec, request)
    dati, errore = aggiorna(grafico, request, forza)
    return {"id": grafico.id_widget, "tipo": "salvato", "titolo": grafico.titolo, "grafico": grafico,
            "serie": serie_di(grafico, dati, vista), "errore": errore, "dom": f"wd-g-{grafico.pk}", "mio": mio,
            "sotto": descrizione(grafico.spec, vista=vista, tipo=grafico.tipo),
            "aggiornato": grafico.aggiornato if mio else timezone.now(),
            "larghezza": 1 if grafico.tipo == Grafico.KPI else 2,
            "tipi": TIPI_SCAMBIABILI if grafico.tipo in Grafico.INTERCAMBIABILI else []}


def widget_leggero(grafico):
    """Solo il titolo: per il cassetto «Aggiungi widget», senza calcolare niente."""
    return {"id": grafico.id_widget, "tipo": "salvato", "titolo": grafico.titolo, "grafico": grafico, "app": "Libreria",
            "w": 1 if grafico.tipo == Grafico.KPI else 2}


def csv_di(grafico, dati):
    uscita = io.StringIO()
    scrittore = csv.writer(uscita, delimiter=";")
    if grafico.tipo == Grafico.PREVISIONE:
        scrittore.writerow(["Periodo", "Valore", "Previsione 10 %", "Previsione mediana", "Previsione 90 %"])
        scrittore.writerows([[e, v, "", "", ""] for e, v in dati.get("storico", [])])
        scrittore.writerows([[e, "", b, m, a] for e, b, m, a in dati.get("futuro", [])])
    elif grafico.tipo == Grafico.KPI:
        scrittore.writerow(["Periodo", "Valore"])
        scrittore.writerows(dati.get("storico", []))
        scrittore.writerow(["Attuale", dati.get("valore", "")])
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
        elif w["tipo"] == "salvato" and w["serie"]["tipo"] == "kpi":
            kpi.append({"app": w["titolo"], "query": w["sotto"], "indicatori": [
                {"etichetta": "valore", "valore": w["serie"]["valore_testo"]},
                *([{"etichetta": "variazione", "valore": w["serie"]["delta_testo"]}] if w["serie"]["delta_testo"] else [])],
                "storico": w["serie"]["righe"]})
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


def pagina_app(utente, app):
    """(Pagina, info) della scheda dell'app per l'utente, creata al primo accesso così ha titolo e layout suoi;
    (None, None) se l'app non ha indicatori o l'utente non la vede."""
    info = next((a for a in app_con_indicatori(utente) if a["slug"] == app), None)
    if info is None:
        return None, None
    icona = info.get("icon") or "zap"
    p, _ = Pagina.objects.get_or_create(utente=utente, app=app, defaults={
        "titolo": info["label"], "icona": "bar-chart" if "/" in icona else icona})
    return p, info


def nuova_pagina(utente, titolo, icona="bar-chart"):
    from django.db.models import Max
    ordine = (Pagina.objects.filter(utente=utente, app="").aggregate(m=Max("ordine"))["m"] or 0) + 1
    return Pagina.objects.create(utente=utente, titolo=(titolo or "").strip()[:100] or "Nuova pagina", ordine=ordine,
                                 icona=icona if icona in dict(ICONE) else "bar-chart")


def destinazione(utente, valore, titolo_nuova=""):
    """La pagina scelta in un form o da Ada: l'id di una pagina propria, «app:slug», «nuova», il titolo di una pagina
    propria, oppure vuoto (libreria). ValueError se non c'è."""
    valore = (valore or "").strip()
    if not valore:
        return None
    if valore == "nuova":
        return nuova_pagina(utente, titolo_nuova)
    if valore.startswith("app:"):
        p, _ = pagina_app(utente, valore[4:])
        if p is None:
            raise ValueError(f"Nessuna scheda dell'app «{valore[4:]}».")
        return p
    if valore.isdigit():
        p = Pagina.objects.filter(pk=int(valore), utente=utente).first()
    else:
        p = Pagina.objects.filter(utente=utente, titolo__iexact=valore).first()
    if p is None:
        raise ValueError(f"Nessuna pagina «{valore}».")
    return p


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
