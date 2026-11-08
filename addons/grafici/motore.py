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

from core import barra
from core import dashboard as dash
from core import parametri
from core.models import Ruolo
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
PANORAMICA = "panoramica"
MAX_SCHEDE_PAGINE = 6                                    # in vista nella riga delle schede; le altre nel menu «Altre schede»
MAX_SCHEDE_APP = 3                                       # le app personalizzate in vista


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


def _tabella(spec, request):
    """Le righe di una tabella salvata dalla chat, ricalcolate con lo stesso codice dell'assistente (colonne, link)."""
    if not _ai_disponibile():
        raise ErroreInterrogazione("Le tabelle salvate dalla chat richiedono il modulo Assistente AI.")
    from ai.artifact import calcola
    from ai.strumenti import Contesto, ErroreStrumento
    try:
        return calcola({**spec, "tipo": "tabella"}, Contesto(utente=request.user, azienda=getattr(request, "azienda", None)))
    except ErroreStrumento as e:
        raise ErroreInterrogazione(str(e)) from e


def dati_di(tipo, spec, request):
    """I dati di una specifica per l'utente della richiesta: {"serie", "chiavi", "totale"}, per i KPI {"valore",
    "precedente", "delta", "storico"}, per le previsioni {"storico", "futuro", "totale", "modello"}."""
    if tipo == Grafico.PREVISIONE:
        return _previsione(spec, request)
    if tipo == Grafico.TABELLA:
        return _tabella(spec, request)
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
    if grafico.tipo == Grafico.TABELLA:
        righe = dati.get("righe", [])
        return {"tipo": "tabella", "titolo": grafico.titolo, "colonne": dati.get("colonne", []), "righe": righe,
                "link": dati.get("link", []), "totale": dati.get("totale"), "vuoto": not righe}
    if grafico.tipo == Grafico.KPI:
        storico = [tuple(c) for c in dati.get("storico", [])]
        delta = dati.get("delta")
        nomi = interroga.NOMI_PERIODO.get(dati.get("periodo", ""), ("", ""))
        obiettivo = (grafico.opzioni or {}).get("obiettivo")
        valore = dati.get("valore")
        percento = round(float(valore) * 100 / float(obiettivo)) if obiettivo and valore is not None else None
        return {"tipo": "kpi", "titolo": grafico.titolo, "valore": valore, "unita": dati.get("unita", ""),
                "obiettivo": obiettivo, "obiettivo_testo": testo_valore(obiettivo, dati.get("unita", "")) if obiettivo else "",
                "percento": min(percento, 100) if percento is not None else None, "percento_testo": f"{percento} %" if percento is not None else "",
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
            "link": link if any(link) else [], "obiettivo": (grafico.opzioni or {}).get("obiettivo")}


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


def widget_leggero(grafico, request):
    """Il grafico nella libreria: i dati si calcolano solo se finisce in vista (`carica`)."""
    return {"id": grafico.id_widget, "tipo": "salvato", "titolo": grafico.titolo, "grafico": grafico, "su_richiesta": True,
            "app": "I tuoi grafici" if grafico.utente_id == request.user.id else f"Condiviso da {_nome(grafico.utente)}",
            "larghezza": 1 if grafico.tipo == Grafico.KPI else 2, "template": "grafici/_widget.html",
            "carica": lambda: widget_salvato(grafico, request)}


def libreria_di(utente):
    """I grafici che una persona può mettere nelle sue pagine: i suoi e quelli condivisi con lei."""
    return Grafico.objects.filter(Q(utente=utente) | Q(condiviso_con=utente)).select_related("utente").distinct().order_by("titolo", "pk")


def widget_per_panoramica(request):
    return [widget_leggero(g, request) for g in libreria_di(request.user)]


def condivise(azienda, utente=None):
    """Le pagine che chi guarda riceve dai colleghi dell'azienda: quelle condivise con tutta l'azienda e, se si dà
    `utente`, quelle condivise con il suo ruolo o con un suo gruppo. Senza un'azienda corrente, nessuna."""
    if azienda is None:
        return Pagina.objects.none()
    per_chi = Q(condivisa=True)
    if utente is not None:
        ruolo = Ruolo.objects.filter(profili__utente=utente).values_list("pk", flat=True).first()
        if ruolo:
            per_chi |= Q(ruoli=ruolo)
        gruppi = list(utente.groups.values_list("pk", flat=True))
        if gruppi:
            per_chi |= Q(gruppi__in=gruppi)
    pk = Pagina.objects.filter(per_chi, utente__profilo__aziende=azienda).values("pk")
    return Pagina.objects.filter(pk__in=pk)


def a_chi(pagina):
    """Con chi è condivisa, in parole: «tutta l'azienda», «i ruoli Commerciale, Direzione», «» se con nessuno."""
    if pagina.condivisa:
        return "tutta l'azienda"
    nomi = [*(f"ruolo {r}" for r in pagina.ruoli.all()), *(f"gruppo {g}" for g in pagina.gruppi.all())]
    return ", ".join(nomi)


def puo_vedere(grafico, utente, azienda):
    """Il proprietario, chi lo ha ricevuto, chi vede una pagina condivisa del proprietario che lo contiene e i membri
    di un'area di lavoro la cui dashboard lo contiene."""
    if grafico.utente_id == utente.id or grafico.condiviso_con.filter(pk=utente.pk).exists():
        return True
    if any(grafico.id_widget in p.id_widget for p in condivise(azienda, utente).filter(utente_id=grafico.utente_id)):
        return True
    return any(grafico.id_widget in p.id_widget and area_visibile(utente, azienda, p.area)
               for p in Pagina.objects.filter(area__isnull=False))


# ---------- dashboard delle aree di lavoro dell'assistente ----------

def _aree_disponibili():
    return _ai_disponibile()


def area_visibile(utente, azienda, area_pk):
    """L'area di lavoro dell'assistente se l'utente la vede (sua o di cui è membro), altrimenti None."""
    if not _aree_disponibili() or not area_pk:
        return None
    from ai import aree
    return aree.visibile(utente, azienda, area_pk)


def pagina_area(utente, azienda, area_pk):
    """(Pagina, area) della dashboard dell'area, creata al primo accesso a nome di chi ha creato l'area;
    (None, None) se l'utente non vede l'area."""
    area = area_visibile(utente, azienda, area_pk)
    if area is None:
        return None, None
    p, _ = Pagina.objects.get_or_create(area=area.pk, defaults={
        "utente_id": area.utente_id, "titolo": f"Dashboard · {area.nome}"[:100], "icona": "bar-chart"})
    return p, area


def url_pagina(p):
    if p.area:
        return reverse("grafici:pagina_area", args=[p.area])
    return reverse("grafici:pagina_app", args=[p.app]) if p.app else reverse("grafici:pagina", args=[p.pk])


def pagine_con(grafico, utente):
    return [p for p in Pagina.objects.filter(utente=utente) if grafico.id_widget in p.id_widget]


def _aggiungi(layout, id_widget):
    layout = dict(layout or {})
    voci = list(layout.get("widget", []))
    if id_widget not in [v.get("id") for v in voci if isinstance(v, dict)]:
        voci.append({"id": id_widget})
    layout["widget"] = voci
    layout["nascosti"] = [i for i in layout.get("nascosti", []) if i != id_widget]
    return layout


def _senza(layout, id_widget):
    layout = dict(layout or {})
    layout["widget"] = [v for v in layout.get("widget", []) if not (isinstance(v, dict) and v.get("id") == id_widget)]
    return layout


def metti_in_pagina(pagina, grafico):
    pagina.layout = _aggiungi(pagina.layout, grafico.id_widget)
    pagina.save(update_fields=["layout", "aggiornata"])


def togli_da_pagina(pagina, grafico):
    pagina.layout = _senza(pagina.layout, grafico.id_widget)
    pagina.save(update_fields=["layout", "aggiornata"])


def in_panoramica(grafico, utente):
    return grafico.id_widget in [v.get("id") for v in dash.layout_di(utente).get("widget", []) if isinstance(v, dict)]


def imposta_panoramica(grafico, utente, dentro):
    from core.models import DashboardUtente
    layout = dash.layout_di(utente)
    if dentro and not in_panoramica(grafico, utente):
        layout = _aggiungi(layout, grafico.id_widget)
    elif not dentro and in_panoramica(grafico, utente):
        layout = _senza(layout, grafico.id_widget)
    else:
        return
    DashboardUtente.objects.update_or_create(utente=utente, defaults={"layout": layout})


def metti_in(utente, valore, grafico, titolo_nuova="", azienda=None):
    """Mette il grafico dove indica un form o Ada; (titolo, indirizzo) del posto, o (None, None) se resta solo in libreria."""
    if (valore or "").strip() == PANORAMICA:
        imposta_panoramica(grafico, utente, True)
        return "Panoramica", reverse("core:dashboard")
    p = destinazione(utente, valore, titolo_nuova, azienda)
    if p is None:
        return None, None
    metti_in_pagina(p, grafico)
    return p.titolo, url_pagina(p)


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

def _voci_pagina(pagina, request):
    """Tutti i widget che possono stare nella pagina. Quelli delle app sono di partenza solo nella scheda della loro app."""
    voci = []
    for w in dash.catalogo(request, extra=False)[0]:
        voci.append({**w, "su_richiesta": w["id"].split(":", 1)[0] != pagina.app})
    if pagina.area:                                       # dashboard di un'area: i grafici di tutti i membri che ci sono,
        presenti = [int(i[2:]) for i in pagina.id_widget if i.startswith("g:") and i[2:].isdigit()]   # più i propri
        grafici = Grafico.objects.filter(Q(pk__in=presenti) | Q(utente=request.user) | Q(condiviso_con=request.user))
        return voci + [widget_leggero(g, request) for g in grafici.select_related("utente").distinct()]
    if pagina.utente_id == request.user.id:
        voci += [widget_leggero(g, request) for g in libreria_di(request.user)]
    else:                                                 # pagina condivisa: i grafici del proprietario, non quelli di chi guarda
        voci += [widget_leggero(g, request) for g in Grafico.objects.filter(utente_id=pagina.utente_id).select_related("utente")]
    return voci


def catalogo(pagina, request):
    """(in vista, in libreria): i widget della pagina, già con i dati, e quelli che si possono aggiungere."""
    visibili, nascosti = dash.disponi(pagina.layout, _voci_pagina(pagina, request))
    return dash.carica(visibili), nascosti if pagina.utente_id == request.user.id or pagina.area else []


def salva_layout(pagina, dati, request):
    """Il layout dal client, validato come quello della dashboard: passano solo i widget che la pagina può mostrare."""
    layout = dash.layout_valido(dati, _voci_pagina(pagina, request))
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
    """Le schede della dashboard per chi guarda, in una riga che non scorre mai. In vista: le sue pagine, quelle condivise
    con lui, le app che ha personalizzato (con un limite) e quella aperta. Tutto il resto sta nel menu «Altre schede»,
    per area: {"visibili": [...], "pagine": [...], "gruppi": [{"titolo", "voci"}]}."""
    utente = request.user
    pagine = list((Pagina.objects.filter(utente=utente) | condivise(request.azienda, utente)).filter(area__isnull=True)
                  .distinct().select_related("utente"))
    libere = []
    for p in sorted([p for p in pagine if not p.app], key=lambda p: (p.utente_id != utente.id, p.ordine, p.pk)):
        libere.append({"chiave": p.chiave, "titolo": p.titolo, "icona": p.icona, "immagine": "", "app": False,
                       "url": reverse("grafici:pagina", args=[p.pk]), "condivisa": p.utente_id != utente.id,
                       "proprietario": _nome(p.utente), "attiva": p.chiave == attiva})
    proprie_app = {p.app: p for p in pagine if p.app and p.utente_id == utente.id}
    app = []
    for a in app_con_indicatori(utente):
        p = proprie_app.get(a["slug"])
        if p and p.nascosta:
            continue
        icona = a.get("icon") or "zap"
        app.append({"chiave": f"app:{a['slug']}", "titolo": p.titolo if p else a["nav_label"], "app": True, "categoria": a.get("category", ""),
                    "icona": "" if "/" in icona else icona, "immagine": icona if "/" in icona else "",
                    "url": reverse("grafici:pagina_app", args=[a["slug"]]), "condivisa": False, "proprietario": "",
                    "attiva": f"app:{a['slug']}" == attiva, "personalizzata": bool(p and p.layout)})
    in_vista_libere = libere[:MAX_SCHEDE_PAGINE]
    aperta_nascosta = next((v for v in libere[MAX_SCHEDE_PAGINE:] if v["attiva"]), None)
    if aperta_nascosta:                                   # la scheda aperta non finisce mai nel menu
        in_vista_libere = [*in_vista_libere[:-1], aperta_nascosta]
    personalizzate = [v for v in app if v["personalizzata"]][:MAX_SCHEDE_APP]
    in_vista_app = personalizzate + [v for v in app if v["attiva"] and v not in personalizzate]
    in_menu = [v for v in app if v not in in_vista_app]
    return {"visibili": in_vista_libere + in_vista_app, "pagine": [v for v in libere if v not in in_vista_libere],
            "gruppi": barra.gruppi(in_menu, "titolo")}


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


def destinazione(utente, valore, titolo_nuova="", azienda=None):
    """La pagina scelta in un form o da Ada: l'id di una pagina propria, «app:slug», «area:id» (la dashboard di
    un'area di lavoro dell'assistente), «nuova», il titolo di una pagina propria, oppure vuoto (libreria).
    ValueError se non c'è."""
    valore = (valore or "").strip()
    if not valore:
        return None
    if valore == "nuova":
        return nuova_pagina(utente, titolo_nuova)
    if valore.startswith("area:"):
        p, _ = pagina_area(utente, azienda, valore[5:])
        if p is None:
            raise ValueError("Area di lavoro inesistente o non tua.")
        return p
    if valore.startswith("app:"):
        p, _ = pagina_app(utente, valore[4:])
        if p is None:
            raise ValueError(f"Nessuna scheda dell'app «{valore[4:]}».")
        return p
    if valore.isdigit():
        p = Pagina.objects.filter(pk=int(valore), utente=utente, area__isnull=True).first()
    else:
        p = Pagina.objects.filter(utente=utente, titolo__iexact=valore, area__isnull=True).first()
    if p is None:
        raise ValueError(f"Nessuna pagina «{valore}».")
    return p


def destinazioni(request, vista="", area=None):
    """[(valore, etichetta)] delle pagine in cui si può salvare un grafico: prima la dashboard dell'area di lavoro
    (se il grafico nasce in una sua chat), la scheda dell'app della vista, le pagine libere dell'utente, le altre app e
    «Nuova pagina»."""
    app_vista = (vista or "").split(".", 1)[0]
    apps = app_con_indicatori(request.user)
    scelte = []
    if area is not None and area_visibile(request.user, getattr(request, "azienda", None), area.pk):
        scelte.append((f"area:{area.pk}", f"Dashboard dell'area «{area.nome}»"))
    scelte += [(f"app:{a['slug']}", f"Scheda {a['label']}") for a in apps if a["slug"] == app_vista]
    scelte.append((PANORAMICA, "Panoramica"))
    scelte += [(str(p.pk), p.titolo) for p in Pagina.objects.filter(utente=request.user, app="", area__isnull=True)]
    scelte += [(f"app:{a['slug']}", f"Scheda {a['label']}") for a in apps if a["slug"] != app_vista]
    scelte.append(("nuova", "Nuova pagina…"))
    return scelte
