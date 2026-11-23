"""Fonti riservate: app intere (impostazione per azienda), cartelle dei Documenti (con le sottocartelle) e chat segnate
dall'utente. Una chat che legge una fonte riservata diventa riservata per sempre, e da lì usa solo modelli locali:
il dato riservato non arriva mai a un modello cloud. Senza un modello locale attivo Ada si ferma e non invia nulla."""
import json
import re

from core import parametri

PROFONDITA = 50                                          # come documenti/accesso.py: contro i cicli
STRUMENTI_DOCUMENTO = {"leggi_documento", "leggi_foglio"}
VISTA_DOCUMENTI = "documenti.documenti"
_COPPIA = re.compile(r'"vista":\s*"([^"]+)"[^{}]*?"id":\s*(\d+)')


def app_riservate(azienda):
    try:
        testo = parametri.leggi("ai.app_riservate", azienda) or ""
    except KeyError:
        return set()
    return {s.strip().lower() for s in str(testo).split(",") if s.strip()}


def cartelle_riservate(azienda):
    """{id cartella: percorso della cartella riservata da cui discende}. Calcolata a ogni chiamata (una query)."""
    from . import archivio
    if azienda is None or not archivio.attivo():
        return {}
    from documenti.models import Cartella
    righe = {pk: (padre, riservata, nome) for pk, padre, riservata, nome in
             Cartella.objects.filter(azienda=azienda).values_list("pk", "padre_id", "riservata", "nome")}
    if not any(r[1] for r in righe.values()):
        return {}

    def percorso(pk):
        nomi, visti = [], set()
        while pk in righe and pk not in visti and len(nomi) < PROFONDITA:
            visti.add(pk)
            nomi.append(righe[pk][2])
            pk = righe[pk][0]
        return " / ".join(reversed(nomi))

    risultato = {}
    for pk in righe:
        corrente, visti = pk, set()
        while corrente in righe and corrente not in visti and len(visti) < PROFONDITA:
            visti.add(corrente)
            if righe[corrente][1]:
                risultato[pk] = percorso(corrente)
                break
            corrente = righe[corrente][0]
    return risultato


def _documenti_riservati(azienda, ids):
    """{id documento: percorso della cartella riservata} per gli id dati."""
    cartelle = cartelle_riservate(azienda)
    if not cartelle or not ids:
        return {}
    from documenti.models import Documento
    return {pk: cartelle[c] for pk, c in Documento.objects.filter(pk__in=ids, azienda=azienda)
            .values_list("pk", "cartella_id") if c in cartelle}


def _app_di_misura(nome):
    from core import misure
    try:
        m = misure.per_nome(nome)
    except Exception:
        return [nome.partition(".")[0]]
    return [m.app or nome.partition(".")[0], *(c.vista.partition(".")[0] for c in m.componenti)]


def _coppie(contenuto):
    """Le coppie (vista, id) dei risultati di cerca_conoscenza, anche se il testo è troncato e il JSON è rotto."""
    try:
        dati = json.loads(contenuto)
        return [(r.get("vista", ""), r.get("id")) for r in dati.get("risultati", []) if isinstance(r, dict)]
    except (ValueError, TypeError, AttributeError):
        return [(v, int(i)) for v, i in _COPPIA.findall(contenuto or "")]


def _motivo_coppie(coppie, azienda, app):
    for vista, _ in coppie:
        if vista.partition(".")[0].lower() in app:
            return f"app «{vista.partition('.')[0]}»"
    documenti = _documenti_riservati(azienda, [i for v, i in coppie if v == VISTA_DOCUMENTI and isinstance(i, int)])
    for vista, i in coppie:
        if vista == VISTA_DOCUMENTI and i in documenti:
            return f"cartella «{documenti[i]}»"
    return ""


def _motivo_viste_documenti(nome, argomenti, azienda):
    """cerca_record, leggi_record, aggrega_record e anteprime sulle viste documenti.*: mostrano nomi, descrizioni e
    percorsi. Con un id si guarda il record; senza, se ci sono cartelle riservate la lettura conta come riservata."""
    vista = argomenti.get("vista")
    if not isinstance(vista, str) or vista.partition(".")[0] != "documenti":
        return ""
    cartelle = cartelle_riservate(azienda)
    if not cartelle:
        return ""
    slug = vista.partition(".")[2]
    try:
        pk = int(argomenti.get("id"))
    except (TypeError, ValueError):
        pk = None
    if nome == "leggi_record" and pk is not None and slug in ("documenti", "cartelle"):
        percorso = _documenti_riservati(azienda, [pk]).get(pk) if slug == "documenti" else cartelle.get(pk)
        return f"cartella «{percorso}»" if percorso else ""
    return "Documenti con cartelle riservate"


def fonte_riservata(nome, argomenti, contenuto, azienda, app_strumento=""):
    """Il motivo per cui lo strumento `nome`, chiamato con `argomenti` e con risultato `contenuto`, ha letto una fonte
    riservata; "" se non l'ha fatto. Chi chiama passa solo i risultati riusciti."""
    argomenti = argomenti or {}
    app = app_riservate(azienda)
    if app:
        candidate = []
        # anche i pezzi di una dashboard (analisi_crea_dashboard): ognuno ha la sua vista o misura
        pezzi = argomenti.get("pezzi") if isinstance(argomenti.get("pezzi"), list) else []
        for a in [argomenti, *(p for p in pezzi if isinstance(p, dict))]:
            if isinstance(a.get("vista"), str):
                candidate.append(a["vista"].partition(".")[0])
            for chiave in ("misura_aziendale",) + (("nome",) if nome == "misura" else ()):
                if isinstance(a.get(chiave), str) and a[chiave]:
                    candidate += _app_di_misura(a[chiave])
        if app_strumento:
            candidate.append(app_strumento)
        for a in candidate:
            if a.lower() in app:
                return f"app «{a}»"
        if nome == "analisi_leggi_pagina":                # una pagina di Analisi può mostrare dati di ogni app
            return "pagina di Analisi con app riservate"
    if (motivo := _motivo_viste_documenti(nome, argomenti, azienda)):
        return motivo
    if nome in STRUMENTI_DOCUMENTO:
        try:
            pk = int(argomenti.get("id"))
        except (TypeError, ValueError):
            return ""
        percorso = _documenti_riservati(azienda, [pk]).get(pk)
        return f"cartella «{percorso}»" if percorso else ""
    if nome == "cerca_conoscenza":
        return _motivo_coppie(_coppie(contenuto), azienda, app)
    return ""


def risultati_ammessi(risultati, azienda):
    """I risultati di cerca_conoscenza che non vengono da fonti riservate."""
    app = app_riservate(azienda)
    documenti = _documenti_riservati(azienda, [r.get("id") for r in risultati
                                               if r.get("vista") == VISTA_DOCUMENTI and isinstance(r.get("id"), int)])
    return [r for r in risultati if str(r.get("vista", "")).partition(".")[0].lower() not in app
            and not (r.get("vista") == VISTA_DOCUMENTI and r.get("id") in documenti)]


def segna(conversazione, motivo):
    """La chat diventa riservata per sempre; resta il primo motivo."""
    if conversazione is None or conversazione.riservata:
        return
    conversazione.riservata, conversazione.riservata_motivo = True, motivo[:200]
    conversazione.save(update_fields=["riservata", "riservata_motivo"])


MESSAGGIO_SENZA_LOCALE = ("Questa chat contiene dati riservati: può rispondere solo un modello locale, e nessuno è "
                          "attivo. Non ho inviato nulla.")


def locali(azienda=None):
    """I modelli sui nostri server che usano strumenti: [(modello, chiave)]."""
    from .models import Modello
    return [(m, m.provider.chiave_per(azienda)) for m in Modello.objects.filter(
        attivo=True, strumenti=True, provider__attivo=True, provider__locale=True).select_related("provider").order_by("pk")]


def filtra(catena, conversazione, azienda=None):
    """La catena per questa chat: invariata se non è riservata; altrimenti i soli anelli locali, o i modelli locali
    attivi se la catena non ne ha. Nessuno: NessunModello, e non parte nulla."""
    if conversazione is None or not getattr(conversazione, "riservata", False):
        return catena
    return solo_locali(catena, azienda)


# ---------- dati che entrano nella chat prima di qualunque strumento ----------

PAGINE_DI_TUTTE = {"", "grafici", "riepilogo"}           # home, Analisi, riepilogo: dati di ogni app
_PAGINA_DOCUMENTI = re.compile(r"^/documenti/(documenti|cartelle)/(\d+)")
USCITE = {"cerca_web", "leggi_pagina"}                   # strumenti che portano testo fuori dal server


def motivo_record(vista, obj, azienda):
    """Il motivo per cui il record `obj` (della vista `vista`) è riservato; "" se non lo è."""
    modulo = (getattr(vista, "modulo", "") or "").lower()
    if modulo and modulo in app_riservate(azienda):
        return f"app «{modulo}»"
    cartelle = cartelle_riservate(azienda)
    if not cartelle:
        return ""
    from documenti.models import Cartella
    pk = obj.pk if isinstance(obj, Cartella) else getattr(obj, "cartella_id", None)
    return f"cartella «{cartelle[pk]}»" if pk in cartelle else ""


def motivo_pagina(url, azienda):
    """Il motivo per cui una pagina (Chiedi ad Ada) mostra dati riservati; "" se non li mostra."""
    from urllib.parse import urlsplit
    percorso = "/" + urlsplit(url or "").path.lstrip("/")
    slug = percorso.lstrip("/").split("/", 1)[0].lower()
    app = app_riservate(azienda)
    if slug in app:
        return f"app «{slug}»"
    if app and slug in PAGINE_DI_TUTTE:
        return "pagina con dati di app riservate"
    if (m := _PAGINA_DOCUMENTI.match(percorso)):
        pk = int(m.group(2))
        percorso_cartella = (_documenti_riservati(azienda, [pk]).get(pk) if m.group(1) == "documenti"
                             else cartelle_riservate(azienda).get(pk))
        return f"cartella «{percorso_cartella}»" if percorso_cartella else ""
    return ""


def motivo_area(conversazione, azienda):
    """Un'area di lavoro la cui cartella è riservata, o ne contiene una: la sua nota elenca i documenti."""
    progetto = getattr(conversazione, "progetto", None) if getattr(conversazione, "progetto_id", None) else None
    radice = getattr(progetto, "cartella_documenti", None)
    if not radice:
        return ""
    cartelle = cartelle_riservate(azienda or progetto.azienda)
    if radice in cartelle:
        return f"cartella «{cartelle[radice]}»"
    from documenti.models import Cartella
    padri = dict(Cartella.objects.filter(pk__in=cartelle).values_list("pk", "padre_id"))
    for pk in cartelle:                                  # una cartella riservata dentro quella dell'area
        visti, corrente = set(), padri.get(pk)
        while corrente and corrente not in visti and len(visti) < PROFONDITA:
            if corrente == radice:
                return f"cartella «{cartelle[pk]}»"
            visti.add(corrente)
            corrente = padri.get(corrente) if corrente in padri else \
                Cartella.objects.filter(pk=corrente).values_list("padre_id", flat=True).first()
    return ""


def solo_locali(catena, azienda=None):
    """Gli anelli locali della catena, o i modelli locali attivi; nessuno: NessunModello, e non parte nulla."""
    restanti = [anello for anello in catena if anello[0].provider.locale] or locali(azienda)
    if not restanti:
        from .catalogo import NessunModello
        raise NessunModello(MESSAGGIO_SENZA_LOCALE)
    return restanti


def senza_uscite(ammessi, conversazione):
    """In una chat riservata, via gli strumenti che portano testo fuori: web e sistemi esterni (MCP)."""
    if not getattr(conversazione, "riservata", False):
        return ammessi
    return {n: s for n, s in ammessi.items() if n not in USCITE and not n.startswith("mcp")}
