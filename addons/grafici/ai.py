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
    return motore.url_pagina(p)


def _mie_e_condivise(contesto):
    return ((Pagina.objects.filter(utente=contesto.utente) | motore.condivise(contesto.azienda, contesto.utente)).distinct()
            .select_related("utente").order_by("app", "ordine", "pk"))


def _trova(contesto, pagina):
    """Una pagina per id o titolo, tra quelle che l'utente vede."""
    testo = str(pagina or "").strip()
    qs = _mie_e_condivise(contesto)
    if testo.startswith("area:"):
        p = motore.pagina_area(contesto.utente, contesto.azienda, testo[5:])[0]
    else:
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


def _specifica_misura(misura_aziendale, tipo, per, periodo, orizzonte, titolo):
    """La spec su una misura aziendale: KPI per periodo, previsione per mese/settimana/giorno, grafico per raggruppamento."""
    from core import misure
    if tipo not in TIPI or tipo == Grafico.TABELLA:
        raise ErroreStrumento(f"«tipo» è uno tra: {', '.join(t for t in TIPI if t != Grafico.TABELLA)}.")
    spec = {"misura_aziendale": misura_aziendale}
    if tipo == Grafico.KPI:
        spec["periodo"] = periodo or "mese"
    elif tipo == Grafico.PREVISIONE:
        spec["per"], spec["orizzonte"] = periodo or "mese", max(1, min(int(orizzonte or 3), 24))
    else:
        if not per:
            raise ErroreStrumento("Un grafico ha bisogno di «per» (un raggruppamento della misura, es. cliente o mese).")
        spec["per"] = per
    try:
        etichetta = misure.per_nome(misura_aziendale).etichetta
    except ErroreInterrogazione as e:
        raise ErroreStrumento(str(e))
    return tipo, spec, titolo or (f"{etichetta} del {spec['periodo']}" if tipo == Grafico.KPI else etichetta)


def _specifica(contesto, titolo, vista, tipo, misura, per, data, periodo, orizzonte, filtri, testo, artifact,
               misura_aziendale=""):
    """(tipo, spec, titolo) da controllare: dall'artifact già in chat oppure dai campi."""
    if misura_aziendale and not artifact:
        return _specifica_misura(misura_aziendale, tipo, per, periodo, orizzonte, titolo)
    if artifact:
        from ai.models import Artifact
        a = Artifact.objects.filter(pk=artifact, utente=contesto.utente).first()
        if a is None:
            raise ErroreStrumento(f"Nessun grafico o tabella n. {artifact} in questa chat.")
        if a.tipo == Artifact.TABELLA:
            return Grafico.TABELLA, {k: v for k, v in a.spec.items() if k != "tipo"}, titolo or a.titolo
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
    if vista is None and not spec.get("misura_aziendale"):          # le misure calcolate non hanno una vista
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
    if testo.startswith("area:"):
        area = motore.area_visibile(contesto.utente, contesto.azienda, testo[5:])
        if area is None:
            raise ErroreStrumento("Area di lavoro inesistente o non tua.")
        return f"dashboard dell'area «{area.nome}»"
    if Pagina.objects.filter(utente=contesto.utente).filter(Q(titolo__iexact=testo) | (Q(pk=int(testo)) if testo.isdigit() else Q())).exists():
        return f"pagina «{testo}»"
    return f"pagina nuova «{testo}»"


def anteprima_salva(contesto, titolo="", vista="", tipo="barre", misura="count", per="", data="", periodo="mese",
                    orizzonte=3, filtri=None, testo="", pagina="", artifact=None, obiettivo=None, misura_aziendale=""):
    tipo, spec, titolo = _specifica(contesto, titolo, vista, tipo, misura, per, data, periodo, orizzonte, filtri, testo, artifact,
                                    misura_aziendale)
    vista_obj, _ = _controlla(contesto, tipo, spec)
    descrizione = motore.descrizione(spec, vista=vista_obj, tipo=tipo)
    titolo = (titolo or descrizione)[:200]
    return {"titolo": f"Salva {'il KPI' if tipo == Grafico.KPI else 'il grafico'} «{titolo}» in Analisi",
            "dettagli": [{"campo": "Query", "dopo": descrizione}, {"campo": "Tipo", "dopo": dict(Grafico.TIPI)[tipo]},
                         *([{"campo": "Obiettivo", "dopo": str(obiettivo)}] if obiettivo else []),
                         {"campo": "Dove", "dopo": _dove(contesto, pagina)}]}


def _origine_url(contesto):
    if getattr(contesto, "conversazione_id", None):
        return reverse("ai:conversazione", args=[contesto.conversazione_id])
    return reverse("ai:conversazione", args=[contesto.conversazione.pk]) if contesto.conversazione else ""


def salva_grafico(contesto, titolo="", vista="", tipo="barre", misura="count", per="", data="", periodo="mese",
                  orizzonte=3, filtri=None, testo="", pagina="", artifact=None, obiettivo=None, misura_aziendale=""):
    tipo, spec, titolo = _specifica(contesto, titolo, vista, tipo, misura, per, data, periodo, orizzonte, filtri, testo, artifact,
                                    misura_aziendale)
    vista_obj, dati = _controlla(contesto, tipo, spec)
    testo_pagina = str(pagina or "").strip()
    try:
        p = motore.destinazione(contesto.utente, testo_pagina, azienda=contesto.azienda)
    except ValueError:
        if testo_pagina.startswith("area:"):
            raise ErroreStrumento("Area di lavoro inesistente o non tua.")
        p = motore.nuova_pagina(contesto.utente, testo_pagina) if not testo_pagina.startswith("app:") else None
        if p is None:
            raise ErroreStrumento(f"Nessuna scheda dell'app «{testo_pagina[4:]}».")
    from django.utils import timezone
    g = Grafico.objects.create(
        utente=contesto.utente, titolo=(titolo or motore.descrizione(spec, vista=vista_obj, tipo=tipo))[:200],
        tipo=tipo, spec=spec, dati=dati, aggiornato=timezone.now(), origine=Grafico.CHAT,
        opzioni={"obiettivo": float(obiettivo)} if obiettivo else {}, origine_url=_origine_url(contesto))
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



# ---------- dashboard fatte da Ada: una pagina nuova con più pezzi, una sola conferma ----------

MAX_PEZZI = 8
MIN_PEZZI = 2


def _titolo_libero(contesto, titolo):
    titolo = (titolo or "").strip()[:100]
    if not titolo:
        raise ErroreStrumento("Serve un titolo per la dashboard.")
    # solo le pagine libere: la scheda di un'app («Vendite») o la dashboard di un'area non impediscono il titolo
    if Pagina.objects.filter(utente=contesto.utente, app="", area__isnull=True, titolo__iexact=titolo).exists():
        raise ErroreStrumento(f"La pagina «{titolo}» esiste già: scegli un altro titolo (per aggiungere un grafico a una "
                              "pagina che c'è già usa analisi_salva_grafico).")
    return titolo


PRIMI_PREDEFINITI = 10


def _periodo_e_primi(spec, tipo, periodo, primi):
    """Un grafico su una misura con una data parte dal periodo chiesto, se è uno dei pulsanti, altrimenti dall'anno;
    raggruppato per cliente, fornitore… mostra i primi N (10 se Ada non dice altro) più «Altro», non 60 barre."""
    from core import misure
    if not spec.get("misura_aziendale") or tipo in (Grafico.KPI, Grafico.PREVISIONE):
        return spec
    con = {**spec, "periodo": periodo if periodo in dict(misure.PULSANTI_PERIODO) else "anno"}
    spec = con if misure.periodo_grafico(con) is not None else spec
    if ":" not in misure.per_nome(spec["misura_aziendale"]).raggruppamenti.get(spec.get("per", ""), ":"):
        spec = {**spec, "primi": max(1, min(int(primi), 50)) if primi not in (None, "") else PRIMI_PREDEFINITI}
    return spec


def _vuoto(tipo, dati):
    """Come la card decide che non c'è niente da mostrare (motore.serie_di): KPI senza valore, previsione senza
    storico, grafico senza nessun valore diverso da zero. Un KPI a zero resta: «scaduto: 0 €» è una notizia."""
    dati = dati or {}
    if tipo == Grafico.KPI:
        return dati.get("valore") is None
    if tipo == Grafico.PREVISIONE:
        return not dati.get("storico")
    return not any(r[1] for r in dati.get("serie") or [] if len(r) > 1)


def prepara_pezzi(contesto, pezzi):
    """(validi, tolti): ogni pezzo calcolato adesso con i permessi dell'utente; i grafici vuoti o sbagliati sono tolti
    con il motivo. Validi: {"tipo", "spec", "titolo", "dati", "descrizione", "obiettivo"}, prima gli indicatori."""
    if not isinstance(pezzi, list) or not all(isinstance(p, dict) for p in pezzi):
        raise ErroreStrumento("«pezzi» è un elenco di oggetti, uno per indicatore o grafico.")
    if len(pezzi) > MAX_PEZZI:
        raise ErroreStrumento(f"Al massimo {MAX_PEZZI} pezzi in una dashboard.")
    validi, tolti = [], []
    for n, pezzo in enumerate(pezzi, 1):
        nome = pezzo.get("titolo") or pezzo.get("misura_aziendale") or pezzo.get("vista") or f"pezzo {n}"
        try:
            if pezzo.get("tipo") == Grafico.TABELLA:
                raise ErroreStrumento("le tabelle non vanno nelle dashboard")
            tipo, spec, titolo = _specifica(
                contesto, pezzo.get("titolo") or "", pezzo.get("vista") or "", pezzo.get("tipo") or Grafico.BARRE,
                pezzo.get("misura") or "count", pezzo.get("per") or "", pezzo.get("data") or "", pezzo.get("periodo") or "mese",
                pezzo.get("orizzonte") or 3, pezzo.get("filtri"), pezzo.get("testo") or "", None, pezzo.get("misura_aziendale") or "")
            spec = _periodo_e_primi(spec, tipo, pezzo.get("periodo"), pezzo.get("primi"))
            vista, dati = _controlla(contesto, tipo, spec)
            obiettivo = float(pezzo["obiettivo"]) if pezzo.get("obiettivo") not in (None, "") else None
        except (ErroreStrumento, ErroreInterrogazione, ValueError, TypeError) as e:
            tolti.append(f"{nome} — {e}")
            continue
        if _vuoto(tipo, dati):
            tolti.append(f"{nome} — nessun dato")
            continue
        descrizione = motore.descrizione(spec, vista=vista, tipo=tipo)
        validi.append({"tipo": tipo, "spec": spec, "titolo": (titolo or descrizione)[:200], "dati": dati,
                       "descrizione": descrizione, "obiettivo": obiettivo})
    validi.sort(key=lambda v: v["tipo"] != Grafico.KPI)          # ordinamento stabile: KPI in testa, poi l'ordine di Ada
    return validi, tolti


def _abbastanza(validi, tolti):
    if len(validi) < MIN_PEZZI:
        motivo = ("; tolti: " + "; ".join(tolti)) if tolti else ""
        raise ErroreStrumento(f"Una dashboard ha bisogno di almeno {MIN_PEZZI} pezzi con dei dati, ne restano "
                              f"{len(validi)}{motivo}.")


def anteprima_crea_dashboard(contesto, titolo, pezzi, icona="bar-chart"):
    titolo = _titolo_libero(contesto, titolo)
    validi, tolti = prepara_pezzi(contesto, pezzi)
    _abbastanza(validi, tolti)
    tipi = dict(Grafico.TIPI)
    return {"titolo": f"Crea la dashboard «{titolo}» con {len(validi)} pezzi",
            "dettagli": [*({"campo": v["titolo"], "dopo": f"{tipi[v['tipo']]} · {v['descrizione']}"} for v in validi),
                         *({"campo": "Tolti", "dopo": t} for t in tolti),
                         {"campo": "Dove", "dopo": "una pagina nuova di Analisi, in coda alle tue"}]}


def crea_dashboard(contesto, titolo, pezzi, icona="bar-chart"):
    from django.db import transaction
    from django.utils import timezone
    titolo = _titolo_libero(contesto, titolo)
    validi, tolti = prepara_pezzi(contesto, pezzi)               # ricalcolati: i dati possono essere cambiati
    _abbastanza(validi, tolti)
    adesso, origine = timezone.now(), _origine_url(contesto)
    with transaction.atomic():
        p = motore.nuova_pagina(contesto.utente, titolo, icona)
        grafici = [Grafico.objects.create(
            utente=contesto.utente, titolo=v["titolo"], tipo=v["tipo"], spec=v["spec"], dati=v["dati"], aggiornato=adesso,
            origine=Grafico.CHAT, origine_url=origine, opzioni={"obiettivo": v["obiettivo"]} if v["obiettivo"] is not None else {})
            for v in validi]
        p.layout = {"widget": [{"id": g.id_widget, "w": 1 if g.tipo == Grafico.KPI else 2} for g in grafici]}
        p.save(update_fields=["layout", "aggiornata"])
    esito = f"Dashboard «{p.titolo}» creata con {len(grafici)} pezzi."
    if tolti:
        esito += " Tolti: " + "; ".join(tolti) + "."
    return {"esito": esito, "url": _url(p), "pagina": p.pk, "grafici": [g.pk for g in grafici]}



# Tracce per Ada: le dashboard tipiche, da adattare alla richiesta. Solo misure aziendali (numeri già verificati);
# Ada mostra solo i pezzi delle misure installate. Il magazzino ha una sola misura e sta con gli acquisti.
COMPOSIZIONI = {
    "Panoramica dell'azienda": [
        {"tipo": "kpi", "misura_aziendale": "fatturazione.fatturato", "periodo": "mese"},
        {"tipo": "kpi", "misura_aziendale": "fatturazione.incassato", "periodo": "mese"},
        {"tipo": "kpi", "misura_aziendale": "fatturazione.scaduto"},
        {"tipo": "kpi", "misura_aziendale": "vendite.ordinato", "periodo": "mese"},
        {"tipo": "barre", "misura_aziendale": "fatturazione.fatturato", "per": "mese"},
        {"tipo": "barre_orizzontali", "misura_aziendale": "fatturazione.fatturato", "per": "cliente"}],
    "Vendite": [
        {"tipo": "kpi", "misura_aziendale": "vendite.ordinato", "periodo": "mese"},
        {"tipo": "kpi", "misura_aziendale": "vendite.preventivi_aperti"},
        {"tipo": "kpi", "misura_aziendale": "vendite.valore_preventivi_aperti"},
        {"tipo": "barre", "misura_aziendale": "vendite.ordinato", "per": "mese"},
        {"tipo": "barre_orizzontali", "misura_aziendale": "vendite.ordinato", "per": "cliente"},
        {"tipo": "torta", "misura_aziendale": "vendite.ordinato", "per": "commerciale"}],
    "Fatturazione e incassi": [
        {"tipo": "kpi", "misura_aziendale": "fatturazione.fatturato", "periodo": "mese"},
        {"tipo": "kpi", "misura_aziendale": "fatturazione.incassato", "periodo": "mese"},
        {"tipo": "kpi", "misura_aziendale": "fatturazione.da_incassare"},
        {"tipo": "kpi", "misura_aziendale": "fatturazione.scaduto"},
        {"tipo": "linee", "misura_aziendale": "fatturazione.fatturato", "per": "mese"},
        {"tipo": "barre_orizzontali", "misura_aziendale": "fatturazione.scaduto", "per": "cliente"}],
    "Acquisti e scorte": [
        {"tipo": "kpi", "misura_aziendale": "acquisti.acquistato", "periodo": "mese"},
        {"tipo": "kpi", "misura_aziendale": "magazzino.sotto_scorta"},
        {"tipo": "barre", "misura_aziendale": "acquisti.acquistato", "per": "mese"},
        {"tipo": "barre_orizzontali", "misura_aziendale": "acquisti.acquistato", "per": "fornitore"}],
}


def _pezzo_a_parole(p):
    parti = [p["tipo"], p["misura_aziendale"]]
    if p.get("per"):
        parti.append(f"per {p['per']}")
    if p.get("periodo"):
        parti.append(f"periodo {p['periodo']}")
    return " ".join(parti)


def testo_composizioni():
    """Le composizioni con le sole misure installate; quelle che restano con meno di 2 pezzi non si mostrano."""
    from core import misure
    installate = {m.nome for m in misure.tutte()}
    righe = []
    for nome, pezzi in COMPOSIZIONI.items():
        ci_sono = [p for p in pezzi if p["misura_aziendale"] in installate]
        if len(ci_sono) >= MIN_PEZZI:
            righe.append(f"- {nome}: " + "; ".join(_pezzo_a_parole(p) for p in ci_sono) + ".")
    if not righe:
        return ""
    return ("\nDashboard tipiche, da adattare alla richiesta (per una richiesta diversa scegli tu i pezzi, anche su "
            "viste):\n" + "\n".join(righe))


class _StrumentoDashboard(Strumento):
    """La descrizione porta le composizioni delle misure installate: cambia solo con i moduli."""

    def definizione(self):
        d = super().definizione()
        return {**d, "descrizione": d["descrizione"] + testo_composizioni()}


registra(Strumento(
    "analisi_pagine", "Le pagine di Analisi dell'utente (le schede della sua dashboard) e quelle condivise con lui, "
                      "con quanti widget hanno.",
    {"type": "object", "properties": {}, "required": []}, analisi_pagine, permesso="grafici.view_pagina"))
registra(Strumento(
    "analisi_leggi_pagina", "I numeri di una pagina di Analisi adesso: KPI, grafici salvati con la loro query e i "
                            "dati, previsioni. Per commentare o riassumere una pagina, anche nelle attività pianificate.",
    {"type": "object", "properties": {"pagina": {"type": "string", "description": "titolo o id della pagina, oppure area:id per la dashboard di un'area di lavoro"}},
     "required": ["pagina"]}, analisi_leggi_pagina, permesso="grafici.view_pagina"))
_SCHEMA_SALVA = {"type": "object", "properties": {
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
                                                "app:slug per la scheda di un'app, area:id per la dashboard dell'area di "
                                                "lavoro (quella della chat, se è in un'area); vuoto = libreria"},
    "artifact": {"type": "integer", "description": "id del grafico o della tabella già mostrati in chat: ne copia la query"},
    "obiettivo": {"type": "number", "description": "valore obiettivo: una linea sul grafico, la barra di avanzamento sul KPI"},
    "misura_aziendale": {"type": "string", "description": "una misura dell'elenco «Misure aziendali» al posto di vista e "
                                                          "misura (per i KPI: periodo = giorno, settimana, mese o anno)"}},
 "required": []}

registra(Strumento(
    "analisi_salva_grafico", "Salva in una pagina di Analisi un grafico, un KPI o una previsione che si ricalcolano "
                             "da soli: passa «artifact» per salvare il grafico appena disegnato in chat, oppure la "
                             "query (vista, misura, per o data). Si propone all'utente, che conferma.",
    _SCHEMA_SALVA, salva_grafico, rischio="scrittura", concorrente=False, anteprima=anteprima_salva,
    permesso="grafici.add_grafico", ovunque=True))                    # anche dalla chat di un'app: «salvalo in Analisi»
registra(Strumento(
    "analisi_crea_pagina", "Crea una pagina di Analisi vuota (una scheda nuova sulla dashboard). Si propone all'utente, che conferma.",
    {"type": "object", "properties": {"titolo": {"type": "string"},
                                      "icona": {"type": "string", "enum": [i for i, _ in motore.ICONE]}},
     "required": ["titolo"]}, crea_pagina, rischio="scrittura", concorrente=False, anteprima=anteprima_crea_pagina,
    permesso="grafici.add_pagina"))

_PEZZO = {**{k: v for k, v in _SCHEMA_SALVA["properties"].items() if k not in ("pagina", "artifact")},
          "periodo": {"type": "string", "enum": ["giorno", "settimana", "mese", "trimestre", "anno", "anno_scorso"],
                      "description": "kpi: giorno, settimana, mese o anno (default mese); grafici sulle misure: mese, "
                                     "trimestre, anno o anno_scorso (default anno); previsione: mese, settimana, giorno"},
          "primi": {"type": "integer", "description": "grafici sulle misure per cliente, fornitore…: solo i primi N più "
                                                      "«Altro» (default 10)"}}
registra(_StrumentoDashboard(
    "analisi_crea_dashboard", "Crea in un colpo una pagina nuova di Analisi con 2-8 pezzi (indicatori, grafici, "
                              "previsioni) che si ricalcolano da soli: per «fammi una dashboard di…». Metti prima gli "
                              "indicatori, poi 2-4 grafici; i grafici sulle misure partono dall'anno in corso. I pezzi "
                              "senza dati vengono tolti. Si propone all'utente, che conferma una volta sola.",
    {"type": "object", "properties": {
        "titolo": {"type": "string", "description": "titolo della pagina nuova, es. «Vendite»"},
        "icona": {"type": "string", "enum": [i for i, _ in motore.ICONE]},
        "pezzi": {"type": "array", "minItems": MIN_PEZZI, "maxItems": MAX_PEZZI,
                  "items": {"type": "object", "properties": _PEZZO, "required": ["tipo"]}}},
     "required": ["titolo", "pezzi"]}, crea_dashboard, rischio="scrittura", concorrente=False,
    anteprima=anteprima_crea_dashboard, permesso="grafici.add_grafico", timeout=90.0,   # ogni pezzo si calcola
    ovunque=True))                                   # Analisi raccoglie i numeri di tutte le app: anche dalla chat del CRM
