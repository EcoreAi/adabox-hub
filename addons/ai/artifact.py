"""Grafici e tabelle dell'assistente. Il modello scrive solo la specifica (vista, raggruppamento, misura, filtri);
i dati li calcola il codice nel database con i permessi dell'utente e il disegno lo fa il kernel (SVG lato server,
niente codice del modello eseguito). Nella chat si vede l'istantanea del momento; la pagina dell'artifact
ricalcola con i dati di oggi."""
import csv
import io

from django.utils import timezone

from core import svg
from core.viste.interroga import con_altro, etichetta_misura, ordina_gruppi, serie

from .models import Artifact
from .strumenti import Contesto, ErroreStrumento, Strumento, registra, richiesta
from .strumenti.viste import FILTRI, ORDINA_GRUPPI, TESTO, VISTA, _campi_elenco, aggrega, cerca, vista_per

TIPI_GRAFICO = ("barre", "linee", "torta")
MAX_CATEGORIE = 30
MAX_RIGHE_TABELLA = 200


def _serie(gruppi, per):
    """[(etichetta, valore)]: oltre MAX_CATEGORIE le prime per valore più «Altro» (per le date: le ultime)."""
    return serie(gruppi, per, MAX_CATEGORIE)


def _serie_scelta(gruppi, spec):
    """La serie del grafico: con «primi» le prime N più «Altro» (sulle date: gli ultimi N periodi), con «ordina» in
    quell'ordine, altrimenti come sempre."""
    per, primi, ordina = spec["per"], spec.get("primi"), spec.get("ordina", "")
    if primi and ":" not in per:
        return con_altro([(g["gruppo"], g["valore"]) for g in gruppi], int(primi))
    if primi:
        return [(g["gruppo"], g["valore"]) for g in gruppi][-int(primi):]
    if ordina:
        return [(g["gruppo"], g["valore"]) for g in ordina_gruppi(gruppi, per, ordina)][:MAX_CATEGORIE]
    return _serie(gruppi, per)


def _tabella_raggruppata(v, request, spec):
    """Una riga per gruppo: [gruppo, valore], dal più grande (o nell'ordine chiesto)."""
    from core.viste.interroga import aziende_di
    r = aggrega(v, request, spec["per"], spec.get("misura", "count"), spec.get("filtri"), spec.get("testo", ""),
                aziende=aziende_di(request, spec.get("aziende")))
    tutti = r.get("gruppi", [])
    gruppi = ordina_gruppi(tutti, spec["per"], spec.get("ordina") or "-valore", spec.get("limite", 50))
    campo = spec["per"].split(":", 1)[0]
    return {"colonne": [str(v.etichetta(campo)), etichetta_misura(v, spec.get("misura", "count"))],
            "righe": [[_cella(g["gruppo"]), g["valore"]] for g in gruppi], "link": [""] * len(gruppi),
            "totale": len(tutti)}


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
    if spec.get("grafico") == "previsione":
        from .specialisti import calcola_previsione
        return calcola_previsione(spec, contesto)
    if spec.get("misura_aziendale"):
        from core import misure
        return misure.serie(spec, richiesta.per(contesto))
    v = vista_per(contesto, spec["vista"])
    request = richiesta.per(contesto)
    if spec["tipo"] == Artifact.GRAFICO:
        from core.viste.interroga import aziende_di
        r = aggrega(v, request, spec["per"], spec.get("misura", "count"), spec.get("filtri"), spec.get("testo", ""),
                    aziende=aziende_di(request, spec.get("aziende")),
                    massimo=None if (spec.get("primi") or spec.get("ordina")) else 100)
        return {"serie": _serie_scelta(r.get("gruppi", []), spec), "totale": r["totale"]}
    if spec.get("per"):
        return _tabella_raggruppata(v, request, spec)
    r = cerca(v, request, spec.get("testo", ""), spec.get("filtri"), spec.get("ordina", ""), spec.get("limite", 50),
              1, spec.get("campi") or None)
    campi = _campi_elenco(v, spec.get("campi") or None, request)
    scelte = r.get("scelte", {})
    colonne = [v.etichetta("__str__")] + [v.etichetta(f.name) for f in campi if f.name != "id"]
    righe = [[x["nome"]] + [_cella(scelte.get(f.name, {}).get(str(x[f.name]), x[f.name])) for f in campi
                            if f.name != "id"] for x in r["risultati"]]
    return {"colonne": colonne, "righe": righe, "link": [x["url"] for x in r["risultati"]], "totale": r["totale"]}


def svg_di(artifact, dati=None):
    dati = dati or artifact.dati
    if artifact.spec.get("grafico") == "previsione":
        from .specialisti import svg_previsione
        return svg_previsione(dati, artifact.titolo)
    serie = [tuple(c) for c in dati.get("serie", [])]
    if not serie:
        return ""
    return svg.DISEGNI[artifact.spec.get("grafico", "barre")](serie, artifact.titolo)


def pdf_di(artifact, dati):
    """Il grafico in PDF per l'archivio: titolo, disegno vettoriale, valori e data dei dati (un SVG da solo non si
    archivia: i file .svg possono contenere script e il kernel li rifiuta)."""
    from html import escape

    from core import report
    HTML = report.weasyprint().HTML                       # ReportNonDisponibile senza Pango
    disegno = svg_di(artifact, dati).replace('font-family="inherit"', 'font-family="Helvetica, Arial, sans-serif"')
    righe = "".join(f"<tr><td>{escape(str(e))}</td><td class='n'>{escape(str(v))}</td></tr>" for e, v in dati.get("serie", []))
    pagina = (f"<html><head><meta charset='utf-8'><style>@page {{ size: A4 landscape; margin: 18mm; }} body {{ font-family: Helvetica, Arial, sans-serif; color: #1d1d1f; }}"
              f" h1 {{ font-size: 18pt; margin: 0 0 4mm; }} p {{ color: #6e6e73; font-size: 9pt; margin: 0 0 6mm; }} svg {{ width: 100%; height: auto; }}"
              f" table {{ border-collapse: collapse; margin-top: 8mm; font-size: 9pt; }} td {{ border-bottom: 1px solid #e5e5ea; padding: 2mm 6mm 2mm 0; }} .n {{ text-align: right; }}</style></head>"
              f"<body><h1>{escape(artifact.titolo)}</h1><p>Dati del {timezone.localtime():%d/%m/%Y %H:%M}</p>{disegno}<table>{righe}</table></body></html>")
    return HTML(string=pagina).write_pdf()


def csv_di(artifact, dati):
    uscita = io.StringIO()
    scrittore = csv.writer(uscita, delimiter=";")
    if "futuro" in dati:
        scrittore.writerow(["Periodo", "Valore", "Previsione 10 %", "Previsione mediana", "Previsione 90 %"])
        scrittore.writerows([[e, v, "", "", ""] for e, v in dati.get("storico", [])])
        scrittore.writerows([[e, "", b, m, a] for e, b, m, a in dati.get("futuro", [])])
    elif artifact.tipo == Artifact.GRAFICO:
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


def _grafico_misura(contesto, misura_aziendale, per, tipo, titolo, aziende, primi, periodo, dal, al, di):
    """Un grafico su una misura aziendale: la spec tiene il nome della misura e il periodo come l'ha detto l'utente
    (relativo: «quest'anno» resta l'anno in corso; date precise: fisse)."""
    from core import misure
    spec = {"tipo": Artifact.GRAFICO, "grafico": tipo, "misura_aziendale": misura_aziendale, "per": per}
    if dal or al:
        spec.update({k: v for k, v in (("dal", dal), ("al", al)) if v})
    elif periodo:
        spec["periodo"] = periodo
    for chiave, valore in (("primi", primi), ("di", di), ("aziende", aziende)):
        if valore:
            spec[chiave] = valore
    dati = calcola(spec, contesto)
    a = _crea(contesto, Artifact.GRAFICO, titolo or misure.titolo(misura_aziendale, spec), spec, dati)
    return {"artifact": a.pk, "titolo": a.titolo, "totale": dati["totale"], "serie": dati["serie"],
            "nota": "Il grafico è disegnato sotto la tua risposta: non rifarlo in testo e non elencare tutti i valori."}


def grafico(contesto, vista="", per="", misura="count", tipo="barre", filtri=None, testo="", titolo="", aziende=None,
            ordina="", primi=None, limite=None, misura_aziendale="", periodo="", dal="", al="", di=""):
    primi = primi or limite                       # «limite» è come lo chiamano spesso i modelli
    if tipo not in TIPI_GRAFICO:
        raise ErroreStrumento(f"«tipo» è uno tra: {', '.join(TIPI_GRAFICO)}.")
    if misura_aziendale:
        return _grafico_misura(contesto, misura_aziendale, per, tipo, titolo, aziende, primi, periodo, dal, al, di)
    if not vista:
        raise ErroreStrumento("Indica «vista» oppure «misura_aziendale».")
    if not per:
        raise ErroreStrumento("Un grafico ha bisogno di «per» (campo o data:mese...).")
    spec = {"tipo": Artifact.GRAFICO, "vista": vista, "per": per, "misura": misura or "count", "grafico": tipo,
            "filtri": filtri or {}, "testo": testo or ""}
    if aziende:
        spec["aziende"] = aziende
    if primi:
        try:
            spec["primi"] = max(1, min(int(primi), MAX_CATEGORIE))
        except (TypeError, ValueError):
            raise ErroreStrumento("«primi» è un numero intero.")
    if ordina:
        spec["ordina"] = ordina
    dati = calcola(spec, contesto)
    a = _crea(contesto, Artifact.GRAFICO, titolo or f"{vista}: {misura or 'count'} per {per}", spec, dati)
    return {"artifact": a.pk, "titolo": a.titolo, "totale": dati["totale"], "serie": dati["serie"],
            "nota": "Il grafico è disegnato sotto la tua risposta: non rifarlo in testo e non elencare tutti i valori."}


def tabella(contesto, vista, testo="", filtri=None, ordina="", campi=None, limite=50, titolo="", per="", misura="count"):
    try:
        limite = max(1, min(int(limite), MAX_RIGHE_TABELLA))
    except (TypeError, ValueError):
        raise ErroreStrumento("«limite» è un numero intero.")
    spec = {"tipo": Artifact.TABELLA, "vista": vista, "testo": testo or "", "filtri": filtri or {},
            "ordina": ordina or "", "campi": list(campi or []), "limite": limite}
    if per:                                        # tabella raggruppata: una riga per gruppo con la misura
        spec.update(per=per, misura=misura or "count")
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
        "filtri": FILTRI, "testo": TESTO, "titolo": {"type": "string", "description": "titolo breve del grafico"},
        "aziende": {"description": "consolidato di più aziende dell'utente: \"tutte\" o una lista di id; vuoto = solo la corrente "
                                   "(con per=azienda il confronto tra aziende)"},
        "ordina": ORDINA_GRUPPI, "primi": {"type": "integer", "description": "solo le prime N categorie per valore, "
                                                                               "il resto in «Altro» (es. 5 per i 5 clienti migliori)"},
        "misura_aziendale": {"type": "string", "description": "una misura dell'elenco «Misure aziendali» al posto di vista e "
                                                              "misura; «per» è un suo raggruppamento (es. cliente, mese)"},
        "periodo": {"type": "string", "description": "con misura_aziendale: periodo detto a parole (anno, mese_scorso...)"},
        "dal": {"type": "string", "description": "con misura_aziendale: AAAA-MM-GG, per anni o date precise"},
        "al": {"type": "string", "description": "con misura_aziendale: AAAA-MM-GG"}},
     "required": ["per"]}, grafico))
registra(Strumento(
    "tabella", "Mostra sotto la risposta una tabella di record (fino a 200) con link ed export CSV: per elenchi lunghi "
               "invece di scriverli nel testo.",
    {"type": "object", "properties": {
        "vista": VISTA, "testo": TESTO, "filtri": FILTRI,
        "ordina": {"type": "string", "description": "campo, con - davanti per decrescente"},
        "campi": {"type": "array", "items": {"type": "string"}, "description": "colonne (default: quelle della lista)"},
        "limite": {"type": "integer", "description": f"righe (max {MAX_RIGHE_TABELLA}, default 50)"},
        "titolo": {"type": "string"},
        "per": {"type": "string", "description": "tabella raggruppata: una riga per gruppo (campo o data:mese) con la misura"},
        "misura": {"type": "string", "description": "con per: count (default) oppure sum:campo, avg:campo"}},
     "required": ["vista"]}, tabella))
