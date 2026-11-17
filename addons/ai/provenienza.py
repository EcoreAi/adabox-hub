"""Provenienza di una risposta, calcolata dal codice a fine turno (non dichiarata dal modello): quali strumenti hanno
fornito i dati, quanti dati personali sono stati protetti, e quali numeri della risposta non compaiono in nessun dato
letto nel turno (guardia sui numeri: segnala, non blocca)."""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .models import Evento

# numeri non attaccati a lettere, barre o trattini (codici, link, date): 1.234,56 · 1234.5 · 42
NUMERO = re.compile(r"(?<![\w/\-.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![\w/\-]|[.,]\d)")
MESI = r"(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)"
# date in cifre, orari e date a parole («lunedì 16 novembre 2026»): non sono dati da verificare
DATA = re.compile(r"\b\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b|\b\d{1,2}:\d{2}\b|\b\d{1,2}\s+" + MESI + r"(?:\s+\d{4})?\b", re.IGNORECASE)
LINK = re.compile(r"\]\([^)]*\)|https?://\S+")
MAX_SEGNALATI = 5
# Da dove viene un dato letto: una pagina web o un file non sono dati del gestionale, e il badge non deve dirlo
FUORI_DAL_GESTIONALE = {"cerca_web": "web", "leggi_pagina": "web", "leggi_allegato": "allegati",
                        "scrivi_documento": "documento", "leggi_documento_chat": "documento", "modifica_documento": "documento"}
ESTERNO = re.compile(r"mcp\d+_")                       # gli strumenti dei sistemi esterni (ai/mcp.py)


def _origine(nome):
    return "esterni" if nome and ESTERNO.match(nome) else FUORI_DAL_GESTIONALE.get(nome)


# ---------- le fonti consultate, da mostrare sotto la risposta

# strumenti che non leggono dati (orientarsi, preparare una scrittura): non sono fonti
NON_FONTI = {"data_e_ora", "app_disponibili", "elenco_viste", "descrivi_vista", "crea_record", "modifica_record", "elimina_record",
             "esegui_bottone", "esegui_azione", "pianifica_attivita", "crea_pianificata", "elenco_pianificate", "ricorda",
             "scrivi_documento", "modifica_documento", "riassunto", "elenco_esperti", "classifica"}
SUI_RECORD = {"cerca_record": "ricerca", "leggi_record": "record", "aggrega_record": "totali", "grafico": "grafico",
              "tabella": "tabella", "previsione": "previsione"}
MAX_FONTI = 30
MAX_NUMERI = 8                      # «Numeri usati»: i risultati dello strumento misura del turno


def _vista(nome):
    """(etichetta, url della lista) di una vista «modulo.slug», o (nome, "") se non si trova."""
    from django.urls import NoReverseMatch, reverse

    from core.viste import registry
    modulo, _, slug = (nome or "").partition(".")
    vista = next((v for v in registry.viste_di(modulo) if v.slug == slug), None)
    if vista is None:
        return nome, ""
    try:
        url = reverse(f"{modulo}:{slug}_lista")
    except NoReverseMatch:
        url = ""
    return str(vista.model._meta.verbose_name_plural).capitalize(), url


def _breve(valore, n=80):
    testo = valore if isinstance(valore, str) else ", ".join(f"{k}: {v}" for k, v in valore.items()) if isinstance(valore, dict) else str(valore)
    return testo if len(testo) <= n else testo[:n - 1] + "…"


def fonte(nome, argomenti):
    """{origine, titolo, dettaglio, url} di una lettura riuscita, o None se lo strumento non legge dati."""
    argomenti = argomenti if isinstance(argomenti, dict) else {}
    if nome in NON_FONTI or not nome:
        return None
    origine = _origine(nome) or "gestionale"
    if nome in SUI_RECORD:
        titolo, url = _vista(argomenti.get("vista"))
        dettaglio = SUI_RECORD[nome]
        if nome == "leggi_record" and argomenti.get("id") is not None:
            dettaglio = f"record n. {argomenti['id']}"
        elif nome == "grafico" and argomenti.get("titolo"):
            dettaglio = f"grafico «{_breve(argomenti['titolo'], 60)}»"
        if argomenti.get("filtri"):
            dettaglio += f" · filtri: {_breve(argomenti['filtri'], 60)}"
        return {"origine": origine, "titolo": titolo, "dettaglio": dettaglio, "url": url}
    if nome == "cerca_web":
        return {"origine": origine, "titolo": "Ricerca sul web", "dettaglio": _breve(argomenti.get("query", "")), "url": ""}
    if nome == "leggi_pagina":
        url = str(argomenti.get("url", ""))
        dominio = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        return {"origine": origine, "titolo": dominio or "Pagina web", "dettaglio": _breve(url, 90),
                "url": url if url.startswith(("http://", "https://")) else ""}
    if nome == "cerca_conoscenza":
        return {"origine": origine, "titolo": "Documenti e note", "dettaglio": _breve(argomenti.get("domanda", "")), "url": ""}
    if nome in ("leggi_allegato", "leggi_foglio", "leggi_immagine"):
        return {"origine": origine, "titolo": "Allegato", "dettaglio": f"n. {argomenti['id']}" if "id" in argomenti else "", "url": ""}
    if nome in ("leggi_documento", "leggi_documento_chat"):
        return {"origine": origine, "titolo": "Documento", "dettaglio": f"n. {argomenti['id']}" if "id" in argomenti else "", "url": ""}
    if origine == "esterni":
        return {"origine": origine, "titolo": "Sistema esterno", "dettaglio": ESTERNO.sub("", nome).replace("_", " "), "url": ""}
    valori = [v for v in argomenti.values() if isinstance(v, (str, int, float)) and str(v).strip()]
    return {"origine": origine, "titolo": nome.replace("_", " ").capitalize(), "dettaglio": _breve(", ".join(map(str, valori))), "url": ""}
def _citate(nome, contenuto, testo):
    """I risultati di cerca_conoscenza o leggi_documento che la risposta cita con il loro link: una fonte ciascuno,
    con il titolo (documento e pagina, pagina della wiki, record) e il link al punto letto. [] se non ne cita."""
    import json
    if nome not in ("cerca_conoscenza", "leggi_documento") or not testo:
        return []
    try:
        dati = json.loads(contenuto or "")
    except (TypeError, ValueError):
        return []
    if not isinstance(dati, dict):
        return []
    if nome == "leggi_documento":
        voci = [{"url": dati.get("url", ""), "fonte": "Documento", "titolo": f"Documento «{dati.get('documento', '')}»"}]
    else:
        voci = dati.get("risultati", [])
    citate = []
    for v in voci:
        url = v.get("url") or ""
        if url and f"]({url})" in testo:
            citate.append({"origine": "documento" if v.get("fonte") == "Documento" else "gestionale",
                           "titolo": v.get("titolo", ""), "dettaglio": "citata nella risposta", "url": url})
    return citate


# «13 settimane», «3 mesi», «2 ore»: parametri della domanda o del periodo, non dati da verificare
UNITA_DI_TEMPO = re.compile(r"\s*(?:secondi|minut[oi]|or[ae]\b|giorn[oi]|settiman[ae]|mes[ei]|trimestr[ei]|"
                            r"semestr[ei]|ann[oi])", re.IGNORECASE)


# «15 pollici», «27''», «500 W», «0,7×», «4K»: misure di un prodotto o di un'impostazione, non importi da verificare
MISURA = re.compile(r"\s*(?:''|\"|×|x\b|pollici\b|W\b|kW\b|kWh\b|V\b|m\b|cm\b|mm\b|km\b|kg\b|g\b|GB\b|TB\b|MB\b|K\b|°|mq\b|m²|m2\b|l\b|ml\b)")
# l'IVA all'italiana: 4, 5, 10, 22% vicino a «IVA» non è un dato dell'azienda
ALIQUOTE_IVA = {Decimal(4), Decimal(5), Decimal(10), Decimal(22)}
# «circa 20.000 €», «sotto i 22.000 €»: valori dichiarati approssimati, si confrontano con un margine
APPROSSIMATO = re.compile(r"(?:circa|quasi|oltre|sotto|sopra|più di|meno di|intorno a|attorno a|fino a|sui|sulle|sugli)\s+(?:i|le|gli|a|ai)?\s*$", re.IGNORECASE)
MARGINE_APPROSSIMATO = Decimal("0.15")


def da_verificare(testo):
    """[(come è scritto, Decimal, approssimato)]: i numeri della risposta da cercare nei dati letti. Fuori date, orari,
    durate, misure, aliquote IVA, numeri piccoli e anni."""
    pulito = DATA.sub(" ", LINK.sub(" ", testo or ""))
    risultato = []
    for m in NUMERO.finditer(pulito):
        if UNITA_DI_TEMPO.match(pulito, m.end()) or MISURA.match(pulito, m.end()):
            continue
        v = _valore(m.group(1))
        if v is None or not _da_verificare(v):
            continue
        intorno = pulito[max(0, m.start() - 25):m.end() + 25].lower()
        if v in ALIQUOTE_IVA and "%" in pulito[m.end():m.end() + 3] and "iva" in intorno:
            continue
        risultato.append((m.group(1), v, bool(APPROSSIMATO.search(pulito[max(0, m.start() - 20):m.start()]))))
    return risultato


def _valore(testo, italiano=True):
    """Decimal di un numero scritto all'italiana (1.234,56) o all'inglese (1234.56, dei dati JSON)."""
    t = testo.replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif italiano and re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def numeri(testo, italiano=True, durate=True):
    """[(come è scritto, Decimal)]; con durate=False salta i numeri seguiti da un'unità di tempo."""
    testo = DATA.sub(" ", LINK.sub(" ", testo or ""))
    risultato = []
    for m in NUMERO.finditer(testo):
        if not durate and UNITA_DI_TEMPO.match(testo, m.end()):
            continue
        v = _valore(m.group(1), italiano)
        if v is not None:
            risultato.append((m.group(1), v))
    return risultato


def _da_verificare(valore):
    """I numeri piccoli interi (conteggi, elenchi) e gli anni non si controllano."""
    if valore == valore.to_integral_value():
        return not (abs(valore) < 10 or 1900 <= valore <= 2100)
    return True


def _trovato(valore, fonti, approssimato=False):
    for f in fonti:
        if approssimato and f and abs(f - valore) <= abs(f) * MARGINE_APPROSSIMATO:
            return True
        if abs(f - valore) < Decimal("0.005"):
            return True
        if valore == valore.to_integral_value() and f.quantize(Decimal(1), rounding=ROUND_HALF_UP) == valore:
            return True                                     # arrotondato all'unità
    return False


def fonti_precedenti(turno, eventi=None):
    """I numeri già letti prima in questa conversazione (risultati degli strumenti e domande dell'utente) e quelli delle
    istruzioni di Ada: in una domanda di seguito («e quelli di ieri?») contano come fonti. Non le risposte di Ada."""
    if turno.conversazione_id is None:
        return []
    eventi = eventi if eventi is not None else list(Evento.objects.filter(turno=turno).order_by("pk"))
    primo = eventi[0].pk if eventi else None
    qs = Evento.objects.filter(conversazione_id=turno.conversazione_id, tipo__in=[Evento.UTENTE, Evento.STRUMENTO])
    if primo is not None:
        qs = qs.filter(pk__lt=primo)
    valori = []
    for ev in qs.order_by("-pk")[:200]:
        if ev.tipo == Evento.UTENTE:
            if not ev.dati.get("richiamo"):
                valori += [v for _, v in numeri(ev.dati.get("testo", ""))]
        else:
            for r in ev.dati.get("risultati", []):
                if not r.get("errore"):
                    valori += [v for _, v in numeri(r.get("contenuto"), italiano=False)]
                    valori += [v for _, v in numeri(r.get("contenuto"))]
    from .motore import prompt
    valori += [v for _, v in numeri(prompt.sistema(None))]
    return valori


def calcola(turno, testo, protetti=0, segnaposto=None):
    """La provenienza della risposta. `segnaposto`: quelli usati nel turno (i valori restano solo nella conversazione)."""
    eventi = list(Evento.objects.filter(turno=turno).order_by("pk"))
    strumenti, letture, fonti, nomi, chiamate_per_id, consultate = [], 0, [], {}, {}, []
    fuori = {"web": 0, "allegati": 0, "esterni": 0, "documento": 0}
    fonti += fonti_precedenti(turno, eventi)
    previsioni, numeri_usati = [], []
    for ev in eventi:
        if ev.tipo == Evento.UTENTE and not ev.dati.get("richiamo"):    # il richiamo della guardia non è una fonte
            fonti += [v for _, v in numeri(ev.dati.get("testo", ""))]
        elif ev.tipo == Evento.ASSISTENTE:
            chiamate = [b for b in ev.dati.get("blocchi", []) if b["tipo"] == "strumento"]
            strumenti += [b["nome"] for b in chiamate]
            nomi.update({b.get("id"): b["nome"] for b in chiamate})
            chiamate_per_id.update({b.get("id"): b for b in chiamate})
        elif ev.tipo == Evento.STRUMENTO:
            for r in ev.dati.get("risultati", []):
                if not r.get("errore"):
                    chiamata = chiamate_per_id.get(r.get("id"), {})
                    if chiamata.get("nome") == "misura" and len(numeri_usati) < MAX_NUMERI:
                        n = _numero_usato(r.get("contenuto"))
                        if n:
                            numeri_usati.append(n)
                    if chiamata.get("nome") == "previsione" and len(previsioni) < 5:
                        p = _affidabilita(r.get("contenuto"))
                        if p:
                            previsioni.append(p)
                    citate = _citate(chiamata.get("nome"), r.get("contenuto"), testo)
                    for f in citate or [fonte(chiamata.get("nome"), chiamata.get("argomenti"))]:
                        if f and f not in consultate and len(consultate) < MAX_FONTI:
                            consultate.append(f)
                    origine = _origine(nomi.get(r.get("id")))
                    if origine:
                        fuori[origine] += 1
                    else:
                        letture += 1
                    fonti += [v for _, v in numeri(r["contenuto"], italiano=False)]
                    fonti += [v for _, v in numeri(r["contenuto"])]
    nella_risposta = da_verificare(testo)
    non_verificati = []
    for t, v, approssimato in nella_risposta:
        if not _trovato(v, fonti, approssimato) and t not in non_verificati:
            non_verificati.append(t)
    if not letture and not any(v for k, v in fuori.items() if k != "documento"):
        # niente letture in questo turno: verificato solo se i numeri vengono dai dati letti prima nella chat
        esito = "conversazione" if not nella_risposta else "senza fonti" if non_verificati else "verificato"
    else:
        esito = "parziale" if non_verificati else "verificato"
    return {"esito": esito, "strumenti": sorted(set(strumenti)), "letture": letture, "letture_web": fuori["web"], "letture_allegati": fuori["allegati"],
            "letture_esterne": fuori["esterni"], "pii": len(segnaposto) if segnaposto is not None else protetti,
            "segnaposto": sorted(segnaposto or []), "fonti": consultate,
            "non_verificati": non_verificati[:MAX_SEGNALATI], "n_non_verificati": len(non_verificati),
            **({"previsioni": previsioni} if previsioni else {}), **({"numeri": numeri_usati} if numeri_usati else {})}


def _affidabilita(contenuto):
    """{titolo, livello, motivi} dal risultato dello strumento previsione (calcolati dal codice, non dal modello)."""
    import json
    try:
        dati = json.loads(contenuto)
        a = dati.get("affidabilita") or {}
    except (TypeError, ValueError, AttributeError):
        return None
    if a.get("livello") not in ("alta", "media", "bassa"):
        return None
    return {"titolo": str(dati.get("titolo", ""))[:120], "livello": a["livello"],
            "motivi": [str(m)[:200] for m in a.get("motivi", [])][:4], "modello": str(dati.get("modello", ""))[:80]}


def _numero_usato(contenuto):
    """{etichetta, valore, valore_testo, unita, periodo, definizione, url} dal risultato dello strumento misura: la
    definizione e il link li mette il codice (core.misure), non il modello."""
    import json
    from core.viste.gruppi import numero
    try:
        dati = json.loads(contenuto)
        valore = dati["valore"]
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    unita = str(dati.get("unita") or "")
    periodo = (dati.get("periodo") or {}).get("etichetta", "")
    return {"etichetta": str(dati.get("etichetta", ""))[:80], "valore": valore, "unita": unita,
            "valore_testo": f"{numero(valore)} {unita}".strip(), "periodo": str(periodo)[:80],
            "definizione": str(dati.get("definizione", ""))[:300], "url": str(dati.get("url", ""))[:500],
            "nota_lista": str(dati.get("nota_lista", ""))[:300]}
