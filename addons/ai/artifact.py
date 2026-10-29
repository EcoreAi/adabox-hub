"""Grafici e tabelle dell'assistente. Il modello scrive solo la specifica (vista, raggruppamento, misura, filtri);
i dati li calcola il codice nel database con i permessi dell'utente e il disegno lo fa il kernel (SVG lato server,
niente codice del modello eseguito). Nella chat si vede l'istantanea del momento; la pagina dell'artifact
ricalcola con i dati di oggi."""
import csv
import io

from django.utils import timezone

from core import svg

from .models import Artifact
from .strumenti import Contesto, ErroreStrumento, Strumento, registra, richiesta
from .strumenti.viste import FILTRI, TESTO, VISTA, _campi_elenco, aggrega, cerca, vista_per

TIPI_GRAFICO = ("barre", "linee", "torta")
MAX_CATEGORIE = 30
MAX_RIGHE_TABELLA = 200


def _serie(gruppi, per):
    """[(etichetta, valore)]: oltre MAX_CATEGORIE le prime per valore più «Altro» (per le date: le ultime)."""
    coppie = [(g["gruppo"], g["valore"]) for g in gruppi]
    if len(coppie) <= MAX_CATEGORIE:
        return coppie
    if ":" in per:
        return coppie[-MAX_CATEGORIE:]
    ordinate = sorted(coppie, key=lambda c: c[1], reverse=True)
    return ordinate[:MAX_CATEGORIE - 1] + [("Altro", round(sum(v for _, v in ordinate[MAX_CATEGORIE - 1:]), 2))]


def _cella(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "sì" if v else "no"
    if isinstance(v, dict):
        return v.get("nome", "")
    if isinstance(v, list):
        return ", ".join(_cella(x) for x in v)
    return str(v)


def calcola(spec, contesto):
    """I dati di una specifica, calcolati ora per l'utente del contesto."""
    v = vista_per(contesto, spec["vista"])
    request = richiesta.per(contesto)
    if spec["tipo"] == Artifact.GRAFICO:
        r = aggrega(v, request, spec["per"], spec.get("misura", "count"), spec.get("filtri"), spec.get("testo", ""))
        return {"serie": _serie(r.get("gruppi", []), spec["per"]), "totale": r["totale"]}
    r = cerca(v, request, spec.get("testo", ""), spec.get("filtri"), spec.get("ordina", ""), spec.get("limite", 50),
              1, spec.get("campi") or None)
    campi = _campi_elenco(v, spec.get("campi") or None)
    scelte = r.get("scelte", {})
    colonne = [v.etichetta("__str__")] + [v.etichetta(f.name) for f in campi if f.name != "id"]
    righe = [[x["nome"]] + [_cella(scelte.get(f.name, {}).get(str(x[f.name]), x[f.name])) for f in campi
                            if f.name != "id"] for x in r["risultati"]]
    return {"colonne": colonne, "righe": righe, "link": [x["url"] for x in r["risultati"]], "totale": r["totale"]}


def svg_di(artifact, dati=None):
    dati = dati or artifact.dati
    serie = [tuple(c) for c in dati.get("serie", [])]
    if not serie:
        return ""
    return svg.DISEGNI[artifact.spec.get("grafico", "barre")](serie, artifact.titolo)


def csv_di(artifact, dati):
    uscita = io.StringIO()
    scrittore = csv.writer(uscita, delimiter=";")
    if artifact.tipo == Artifact.GRAFICO:
        scrittore.writerow(["Gruppo", "Valore"])
        scrittore.writerows(dati.get("serie", []))
    else:
        scrittore.writerow(dati.get("colonne", []))
        scrittore.writerows(dati.get("righe", []))
    return "﻿" + uscita.getvalue()                     # BOM: Excel legge gli accenti


def _crea(contesto, tipo, titolo, spec, dati):
    if contesto.conversazione is None:
        raise ErroreStrumento("Grafici e tabelle si mostrano solo in una chat.")
    return Artifact.objects.create(conversazione=contesto.conversazione, turno=contesto.turno, utente=contesto.utente,
                                   azienda=contesto.azienda, tipo=tipo, titolo=(titolo or "")[:200], spec=spec,
                                   dati=dati)


def grafico(contesto, vista, per, misura="count", tipo="barre", filtri=None, testo="", titolo=""):
    if tipo not in TIPI_GRAFICO:
        raise ErroreStrumento(f"«tipo» è uno tra: {', '.join(TIPI_GRAFICO)}.")
    if not per:
        raise ErroreStrumento("Un grafico ha bisogno di «per» (campo o data:mese...).")
    spec = {"tipo": Artifact.GRAFICO, "vista": vista, "per": per, "misura": misura or "count", "grafico": tipo,
            "filtri": filtri or {}, "testo": testo or ""}
    dati = calcola(spec, contesto)
    a = _crea(contesto, Artifact.GRAFICO, titolo or f"{vista}: {misura or 'count'} per {per}", spec, dati)
    return {"artifact": a.pk, "titolo": a.titolo, "totale": dati["totale"], "serie": dati["serie"],
            "nota": "Il grafico è disegnato sotto la tua risposta: non rifarlo in testo e non elencare tutti i valori."}


def tabella(contesto, vista, testo="", filtri=None, ordina="", campi=None, limite=50, titolo=""):
    try:
        limite = max(1, min(int(limite), MAX_RIGHE_TABELLA))
    except (TypeError, ValueError):
        raise ErroreStrumento("«limite» è un numero intero.")
    spec = {"tipo": Artifact.TABELLA, "vista": vista, "testo": testo or "", "filtri": filtri or {},
            "ordina": ordina or "", "campi": list(campi or []), "limite": limite}
    dati = calcola(spec, contesto)
    a = _crea(contesto, Artifact.TABELLA, titolo or vista, spec, dati)
    return {"artifact": a.pk, "titolo": a.titolo, "righe": len(dati["righe"]), "totale": dati["totale"],
            "colonne": dati["colonne"], "prime_righe": dati["righe"][:10],
            "nota": "La tabella è mostrata sotto la tua risposta (con export CSV): non ricopiarla, commentala."}


def ricalcola(artifact):
    """I dati di oggi per il proprietario dell'artifact (stessi permessi e azienda di quando l'ha chiesto)."""
    contesto = Contesto(utente=artifact.utente, azienda=artifact.azienda, conversazione=artifact.conversazione)
    dati = calcola(artifact.spec, contesto)
    artifact.aggiornato = timezone.now()
    artifact.save(update_fields=["aggiornato"])
    return dati


registra(Strumento(
    "grafico", "Disegna un grafico (barre, linee, torta) con dati calcolati nel database: conteggio o somma di una "
               "vista per campo o per data. Il grafico appare sotto la risposta e l'utente può salvarlo.",
    {"type": "object", "properties": {
        "vista": VISTA, "per": {"type": "string", "description": "raggruppamento: campo (es. stato, cliente) o data "
                                                                 "(es. data:mese, data:anno)"},
        "misura": {"type": "string", "description": "count (default) oppure sum:campo, avg:campo"},
        "tipo": {"type": "string", "enum": list(TIPI_GRAFICO), "description": "default barre; linee per le date"},
        "filtri": FILTRI, "testo": TESTO, "titolo": {"type": "string", "description": "titolo breve del grafico"}},
     "required": ["vista", "per"]}, grafico))
registra(Strumento(
    "tabella", "Mostra sotto la risposta una tabella di record (fino a 200) con link ed export CSV: per elenchi lunghi "
               "invece di scriverli nel testo.",
    {"type": "object", "properties": {
        "vista": VISTA, "testo": TESTO, "filtri": FILTRI,
        "ordina": {"type": "string", "description": "campo, con - davanti per decrescente"},
        "campi": {"type": "array", "items": {"type": "string"}, "description": "colonne (default: quelle della lista)"},
        "limite": {"type": "integer", "description": f"righe (max {MAX_RIGHE_TABELLA}, default 50)"},
        "titolo": {"type": "string"}},
     "required": ["vista"]}, tabella))
