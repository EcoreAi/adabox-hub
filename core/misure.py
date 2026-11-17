"""Misure aziendali: i numeri che un'azienda chiama per nome (fatturato, scaduto, ordinato, sotto scorta...) con una
definizione fissata nel codice, uguale per l'assistente, la dashboard, Analisi e le chat esterne.

Le app le dichiarano con la chiave "misure" del manifest (un modulo che chiama `registra`). Una misura **aggregata** è
fatta di componenti {vista, misura, filtri, segno} calcolate con `interroga.aggrega`, quindi con i permessi, l'azienda
e le regole di chi chiede: il fatturato è l'imponibile delle fatture emesse meno quello delle note di credito. Una
misura **calcolata** è una funzione, per ciò che non è una somma su una vista (i prodotti sotto scorta)."""
import calendar
import datetime
import importlib
import logging
from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.utils import timezone

from .viste import interroga
from .viste.interroga import ErroreInterrogazione

log = logging.getLogger("core.misure")

PERIODI = ("oggi", "ieri", "domani", "settimana", "settimana_scorsa", "settimana_prossima", "mese", "mese_scorso",
           "trimestre", "trimestre_scorso", "anno", "anno_scorso", "ultimi_12_mesi")
CONFRONTI = ("periodo_prima", "anno_prima")
MAX_PRIMI = 100
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]


@dataclass(frozen=True)
class Componente:
    vista: str                                  # es. fatturazione.fatture
    misura: str                                 # count | sum:campo
    filtri: dict = field(default_factory=dict)
    segno: int = 1


@dataclass
class Misura:
    nome: str                                   # app.nome, es. fatturazione.fatturato
    etichetta: str
    definizione: str                            # una frase per l'utente: che cosa si somma
    unita: str = "€"                            # "€" oppure "" (un conteggio)
    sinonimi: tuple = ()
    raggruppamenti: dict = field(default_factory=dict)      # nome semplice → «per» di aggrega: {"mese": "data:mese"}
    periodo_su: str = ""                        # campo data del periodo; "" = misura istantanea (oggi)
    componenti: tuple = ()
    funzione: object = None                     # calcolata: funzione(request, **parametri) -> {valore, righe, url}
    # filtri che dipendono da chi chiede o da oggi: funzione(request, di) -> dict, aggiunto a ogni componente
    filtri_dinamici: object = None
    periodo_predefinito: str = "anno"
    app: str = ""


@dataclass(frozen=True)
class Periodo:
    dal: datetime.date
    al: datetime.date
    etichetta: str
    relativo: bool

    def come_dict(self):
        return {"dal": self.dal.isoformat(), "al": self.al.isoformat(), "etichetta": self.etichetta}


_registro: dict[str, Misura] = {}
_caricati: set = set()


def registra(misura):
    _registro[misura.nome] = misura
    return misura


def carica():
    """Importa i moduli «misure» dei manifest attivi, una volta per processo; un'app rotta non spegne le altre."""
    from .registry import modules
    for slug, m in modules.manifests_attivi().items():
        if not getattr(m, "misure", None) or slug in _caricati:
            continue
        _caricati.add(slug)
        prima = set(_registro)
        try:
            importlib.import_module(m.misure)
        except Exception:
            log.exception("misure di %s (%s)", slug, m.misure)
            continue
        for nome in set(_registro) - prima:
            _registro[nome].app = _registro[nome].app or slug


def tutte():
    """Le misure dei moduli attivi, in ordine di nome (il prompt dell'assistente deve restare identico)."""
    carica()
    from .registry import modules
    attivi = set(modules.manifests_attivi())
    return sorted((m for m in _registro.values() if not m.app or m.app in attivi), key=lambda m: m.nome)


def per_nome(nome):
    for m in tutte():
        if m.nome == nome:
            return m
    raise ErroreInterrogazione(f"La misura «{nome}» non esiste o la sua app non è installata. "
                               f"Misure disponibili: {', '.join(m.nome for m in tutte()) or 'nessuna'}.")


# ---------- periodi ----------

def _oggi():
    return timezone.localdate()


def _fine_mese(anno, mese):
    return datetime.date(anno, mese, calendar.monthrange(anno, mese)[1])


def _sposta_mesi(data, mesi):
    totale = data.year * 12 + data.month - 1 + mesi
    anno, mese = divmod(totale, 12)
    return datetime.date(anno, mese + 1, min(data.day, calendar.monthrange(anno, mese + 1)[1]))


def _etichetta_intervallo(dal, al):
    if dal == al:
        return dal.strftime("%d/%m/%Y")
    if (dal.month, dal.day, al.month, al.day) == (1, 1, 12, 31) and dal.year == al.year:
        return str(dal.year)
    if dal.day == 1 and al == _fine_mese(al.year, al.month) and (dal.year, dal.month) == (al.year, al.month):
        return f"{MESI[dal.month - 1]} {dal.year}"
    return f"dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}"


def risolvi_periodo(periodo="", dal=None, al=None, oggi=None):
    """Il periodo di una richiesta: un nome (intervallo di calendario intero, relativo) oppure dal/al (fissi)."""
    oggi = oggi or _oggi()
    if dal or al:
        dal = _data(dal) if dal else datetime.date(1900, 1, 1)
        al = _data(al) if al else oggi
        if al < dal:
            raise ErroreInterrogazione("«al» viene prima di «dal».")
        return Periodo(dal, al, _etichetta_intervallo(dal, al), False)
    if periodo not in PERIODI:
        raise ErroreInterrogazione(f"«periodo» è uno tra: {', '.join(PERIODI)} (oppure dal e al).")
    lunedi = oggi - datetime.timedelta(days=oggi.weekday())
    trimestre = datetime.date(oggi.year, (oggi.month - 1) // 3 * 3 + 1, 1)
    giorno = datetime.timedelta(days=1)
    intervalli = {
        "oggi": (oggi, oggi, "di oggi"), "ieri": (oggi - giorno, oggi - giorno, "di ieri"),
        "domani": (oggi + giorno, oggi + giorno, "di domani"),
        "settimana": (lunedi, lunedi + 6 * giorno, "di questa settimana"),
        "settimana_scorsa": (lunedi - 7 * giorno, lunedi - giorno, "della settimana scorsa"),
        "settimana_prossima": (lunedi + 7 * giorno, lunedi + 13 * giorno, "della settimana prossima"),
        "mese": (oggi.replace(day=1), _fine_mese(oggi.year, oggi.month), "del mese in corso"),
        "mese_scorso": (_sposta_mesi(oggi.replace(day=1), -1), oggi.replace(day=1) - giorno, "del mese scorso"),
        "trimestre": (trimestre, _sposta_mesi(trimestre, 3) - giorno, "del trimestre in corso"),
        "trimestre_scorso": (_sposta_mesi(trimestre, -3), trimestre - giorno, "del trimestre scorso"),
        "anno": (datetime.date(oggi.year, 1, 1), datetime.date(oggi.year, 12, 31), "dell'anno in corso"),
        "anno_scorso": (datetime.date(oggi.year - 1, 1, 1), datetime.date(oggi.year - 1, 12, 31), "dell'anno scorso"),
        "ultimi_12_mesi": (_sposta_mesi(oggi.replace(day=1), -11), oggi, "degli ultimi 12 mesi"),
    }
    d, a, e = intervalli[periodo]
    return Periodo(d, a, e, True)


def _data(valore):
    if isinstance(valore, datetime.date):
        return valore
    try:
        return datetime.date.fromisoformat(str(valore).strip()[:10])
    except ValueError:
        raise ErroreInterrogazione(f"Data non valida: «{valore}» (formato AAAA-MM-GG).")


def _a_oggi(p, oggi):
    """Un periodo che contiene oggi si ferma a oggi quando lo si confronta (stesso tratto, non l'anno intero)."""
    return Periodo(p.dal, oggi, p.etichetta, p.relativo) if p.dal <= oggi < p.al else p


def _confronto(p, confronta):
    if confronta == "anno_prima":
        return Periodo(_sposta_mesi(p.dal, -12), _sposta_mesi(p.al, -12), "", False)
    durata = p.al - p.dal
    al = p.dal - datetime.timedelta(days=1)
    return Periodo(al - durata, al, "", False)


# ---------- calcolo ----------

def _filtri(m, componente, request, periodo, di):
    filtri = dict(componente.filtri)
    if m.filtri_dinamici:
        filtri.update(m.filtri_dinamici(request, di) or {})
    if periodo is not None and m.periodo_su:
        filtri[f"{m.periodo_su}__gte"] = periodo.dal.isoformat()
        filtri[f"{m.periodo_su}__lte"] = periodo.al.isoformat()
    return filtri


def _per(m, per):
    if not per:
        return ""
    if per not in m.raggruppamenti:
        possibili = ", ".join(m.raggruppamenti) or "nessun raggruppamento"
        raise ErroreInterrogazione(f"La misura «{m.etichetta}» si raggruppa per: {possibili}.")
    return m.raggruppamenti[per]


def _aggrega(m, request, periodo, per, aziende, di):
    """(totale, {chiave: [etichetta, valore]}, ordine delle chiavi, vista della prima componente) sommando le componenti."""
    totale, gruppi, ordine, prima = 0, {}, [], None
    for c in m.componenti:
        try:
            vista = interroga.vista_per_nome(c.vista, request)
            r = interroga.aggrega(vista, request, per, c.misura, _filtri(m, c, request, periodo, di),
                                  con_chiavi=bool(per), aziende=aziende)
        except ErroreInterrogazione as e:
            raise ErroreInterrogazione(f"Misura «{m.etichetta}»: {e}")
        prima = prima or vista
        totale += c.segno * (r["totale"] or 0)
        for g in r.get("gruppi", []):
            chiave = g.get("chiave", g["gruppo"])
            if chiave not in gruppi:
                gruppi[chiave] = [g["gruppo"], 0]
                ordine.append(chiave)
            gruppi[chiave][1] += c.segno * (g["valore"] or 0)
    return _tondo(totale), gruppi, ordine, prima


def _tondo(v):
    return round(v, 2) if isinstance(v, float) else v


def _url_lista(vista, filtri_fissi, m, periodo, extra=None):
    """La lista della vista con i parametri che capisce (f_<campo>, f_<data>_da/_a: core/viste/filtri.py)."""
    try:
        base = vista.url("lista")
    except Exception:
        return ""
    parametri = {f"f_{k}": v for k, v in filtri_fissi.items() if "__" not in k and not isinstance(v, (list, dict))}
    if periodo is not None and m.periodo_su:
        parametri[f"f_{m.periodo_su}_da"] = periodo.dal.isoformat()
        parametri[f"f_{m.periodo_su}_a"] = periodo.al.isoformat()
    parametri.update(extra or {})
    return f"{base}?{urlencode(parametri)}" if parametri else base


def _extra_gruppo(per, chiave):
    nome, _, parte = per.partition(":")
    if not parte:
        return {f"f_{nome}": chiave}
    inizio = _data(chiave)
    fine = interroga.avanti_periodo(inizio, parte) - datetime.timedelta(days=1)
    return {f"f_{nome}_da": inizio.isoformat(), f"f_{nome}_a": fine.isoformat()}


def calcola(nome, request, periodo="", dal=None, al=None, per="", primi=None, confronta="", aziende=None, di=""):
    """Il valore di una misura con la sua definizione e i link ai record. Vedi il docstring del modulo."""
    m = per_nome(nome)
    risultato = {"nome": m.nome, "etichetta": m.etichetta, "definizione": m.definizione, "unita": m.unita,
                 "periodo": None, "gruppi": [], "confronto": None, "url": ""}
    try:
        primi = max(1, min(int(primi), MAX_PRIMI)) if primi not in (None, "") else None
    except (TypeError, ValueError):
        raise ErroreInterrogazione("«primi» è un numero intero.")
    if m.funzione is not None:
        r = m.funzione(request, di=di)
        righe = sorted(r.get("righe", []), key=lambda x: x["valore"], reverse=True)
        risultato.update(valore=r["valore"], url=r.get("url", ""),
                         gruppi=[{"gruppo": x["etichetta"], "valore": x["valore"], "url": x.get("url", "")}
                                 for x in righe[:primi or MAX_PRIMI]])
        return risultato
    periodo_scelto = None
    if m.periodo_su:
        periodo_scelto = risolvi_periodo(periodo or ("" if dal or al else m.periodo_predefinito), dal, al)
        if confronta:
            if confronta not in CONFRONTI:
                raise ErroreInterrogazione(f"«confronta» è uno tra: {', '.join(CONFRONTI)}.")
            periodo_scelto = _a_oggi(periodo_scelto, _oggi())
        risultato["periodo"] = periodo_scelto.come_dict()
    aziende = interroga.aziende_di(request, aziende)
    per_campo = _per(m, per)
    totale, gruppi, ordine, vista = _aggrega(m, request, periodo_scelto, per_campo, aziende, di)
    principale = m.componenti[0]
    risultato["valore"] = totale
    risultato["url"] = _url_lista(vista, principale.filtri, m, periodo_scelto)
    if per_campo:
        elenco = [(k, gruppi[k][0], _tondo(gruppi[k][1])) for k in ordine]
        if ":" not in per_campo or primi:
            elenco.sort(key=lambda x: x[2], reverse=True)
        if primi:
            elenco = elenco[:primi]
        risultato["gruppi"] = [{"gruppo": e, "valore": v, "chiave": k,
                                "url": _url_lista(vista, principale.filtri, m, periodo_scelto, _extra_gruppo(per_campo, k))
                                if k is not None else ""} for k, e, v in elenco]
    if confronta and periodo_scelto is not None:
        p = _confronto(periodo_scelto, confronta)
        precedente, _, _, _ = _aggrega(m, request, p, "", aziende, di)
        delta = round((totale - precedente) * 100 / precedente, 1) if precedente else None
        risultato["confronto"] = {"valore": precedente, "delta_percento": delta,
                                  "periodo": {**p.come_dict(), "etichetta": _etichetta_intervallo(p.dal, p.al)}}
    return risultato


def testo_prompt():
    """Una riga per misura, per il prompt dell'assistente: cambia solo con i moduli installati."""
    righe = []
    for m in tutte():
        riga = f"- {m.nome} — {m.etichetta}: {m.definizione}."
        if m.sinonimi:
            riga += f" Detta anche: {', '.join(m.sinonimi)}."
        if m.raggruppamenti:
            riga += f" Per: {', '.join(m.raggruppamenti)}."
        if not m.periodo_su:
            riga += " Situazione di oggi (senza periodo)."
        righe.append(riga)
    return "\n".join(righe)


# ---------- grafici, KPI e previsioni sulle misure (spec con "misura_aziendale") ----------

def vista_principale(nome, request):
    """La vista della prima componente (per i link e i permessi dei grafici salvati); None per le calcolate."""
    m = per_nome(nome)
    if not m.componenti:
        return None
    try:
        return interroga.vista_per_nome(m.componenti[0].vista, request)
    except ErroreInterrogazione:
        return None


def titolo(nome, spec=None):
    """«Fatturato dell'anno in corso» (periodo relativo) oppure «Fatturato 2026» (date fisse)."""
    m = per_nome(nome)
    spec = spec or {}
    if not m.periodo_su:
        return m.etichetta
    p = risolvi_periodo(spec.get("periodo") or ("" if spec.get("dal") or spec.get("al") else m.periodo_predefinito),
                        spec.get("dal"), spec.get("al"))
    return f"{m.etichetta} {p.etichetta}"


def _parametri(spec):
    return {"periodo": spec.get("periodo", ""), "dal": spec.get("dal"), "al": spec.get("al"), "di": spec.get("di", ""),
            "aziende": spec.get("aziende")}


def serie(spec, request):
    """La serie di un grafico su una misura: stessa forma di interroga.calcola."""
    nome, per = spec["misura_aziendale"], spec.get("per", "")
    m = per_nome(nome)
    if not per:
        raise ErroreInterrogazione(f"Un grafico ha bisogno di «per»: {', '.join(m.raggruppamenti) or 'nessuno'}.")
    r = calcola(nome, request, per=per, **_parametri(spec))
    temporale = ":" in m.raggruppamenti.get(per, "")
    gruppi = r["gruppi"]
    primi = spec.get("primi")
    if primi and not temporale:
        primi = int(primi)
        valori = interroga.con_altro([(g["gruppo"], g["valore"]) for g in gruppi], primi)
        chiavi = [g.get("chiave") for g in gruppi[:primi]] + ([None] if len(gruppi) > primi else [])
    else:
        valori, chiavi = [(g["gruppo"], g["valore"]) for g in gruppi], [g.get("chiave") for g in gruppi]
    return {"serie": valori, "chiavi": chiavi, "totale": r["valore"], "misura": nome, "per": per}


def kpi(spec, request, storia=12):
    """Il KPI di una misura: valore del periodo in corso, quello prima, delta % e gli ultimi `storia` periodi
    (stessa forma di interroga.kpi)."""
    nome = spec["misura_aziendale"]
    m = per_nome(nome)
    if not m.periodo_su:
        r = calcola(nome, request, di=spec.get("di", ""), aziende=spec.get("aziende"))
        return {"valore": r["valore"], "precedente": None, "delta": None, "storico": [], "periodo": "", "unita": m.unita}
    periodo = spec.get("periodo", "mese") or "mese"
    if periodo not in m.raggruppamenti or periodo not in interroga.PERIODI:
        raise ErroreInterrogazione(f"Il KPI di «{m.etichetta}» va per: "
                                   f"{', '.join(p for p in interroga.PERIODI if p in m.raggruppamenti)}.")
    attuale = interroga.inizio_periodo(_oggi(), periodo)
    primo = interroga.avanti_periodo(attuale, periodo, -(storia - 1))
    fine = interroga.avanti_periodo(attuale, periodo, 1) - datetime.timedelta(days=1)
    r = calcola(nome, request, dal=primo, al=fine, per=periodo, di=spec.get("di", ""), aziende=spec.get("aziende"))
    valori = {g["chiave"]: g["valore"] for g in r["gruppi"]}
    periodi = [interroga.avanti_periodo(primo, periodo, i) for i in range(storia)]
    valore = valori.get(attuale.isoformat(), 0)
    precedente = valori.get(interroga.avanti_periodo(attuale, periodo, -1).isoformat(), 0)
    delta = round((valore - precedente) * 100 / precedente, 1) if precedente else None
    return {"valore": valore, "precedente": precedente, "delta": delta, "periodo": periodo, "unita": m.unita,
            "storico": [(interroga.etichetta_periodo(p, periodo), valori.get(p.isoformat(), 0)) for p in periodi]}


def storia(nome, request, per, aziende=None, di=""):
    """{inizio del periodo: valore} di tutta la storia fino a oggi, per le previsioni."""
    m = per_nome(nome)
    if not m.periodo_su or per not in m.raggruppamenti:
        raise ErroreInterrogazione(f"La misura «{m.etichetta}» non ha una storia per {per}.")
    r = calcola(nome, request, dal=datetime.date(1900, 1, 1), al=_oggi(), per=per, aziende=aziende, di=di)
    return {_data(g["chiave"]): float(g["valore"] or 0) for g in r["gruppi"] if g.get("chiave")}
