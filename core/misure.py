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

from django.db import models
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
    permesso: str | None = None                 # "app.codename" richiesto (le calcolate non passano dalle viste)
    # parametri della lista per il link «apri i record» quando i filtri non si traducono da soli (es. tipo__in),
    # con la nota su ciò che la lista mostra in più; senza, un filtro che la lista non sa applicare toglie il link
    filtri_lista: dict | None = None
    nota_lista: str = ""


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
    attivi = set(modules.manifests_attivi()) - set(modules.disattivati())     # spenti a mano o fuori licenza: fuori
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


# di quanto si torna indietro per «il periodo prima» di un periodo con nome: mesi o giorni di calendario
PASSI = {"mese": (1, 0), "mese_scorso": (1, 0), "trimestre": (3, 0), "trimestre_scorso": (3, 0), "anno": (12, 0),
         "anno_scorso": (12, 0), "ultimi_12_mesi": (12, 0), "settimana": (0, 7), "settimana_scorsa": (0, 7),
         "settimana_prossima": (0, 7), "oggi": (0, 1), "ieri": (0, 1), "domani": (0, 1)}


def _confronto(p, confronta, nome=""):
    if confronta == "anno_prima":
        return Periodo(_sposta_mesi(p.dal, -12), _sposta_mesi(p.al, -12), "", False)
    if nome in PASSI:                                # il mese prima, il trimestre prima...: stesso tratto di calendario
        mesi, giorni = PASSI[nome]
        if mesi:
            al = _sposta_mesi(p.al, -mesi)
            if p.al == _fine_mese(p.al.year, p.al.month):           # fine mese resta fine mese (31/10 → 30/09)
                al = _fine_mese(al.year, al.month)
            return Periodo(_sposta_mesi(p.dal, -mesi), al, "", False)
        passo = datetime.timedelta(days=giorni)
        return Periodo(p.dal - passo, p.al - passo, "", False)
    durata = p.al - p.dal
    al = p.dal - datetime.timedelta(days=1)
    return Periodo(al - durata, al, "", False)


# ---------- calcolo ----------

def _filtri(m, componente, request, periodo, di, scelti=None):
    filtri = dict(componente.filtri)
    if m.filtri_dinamici:
        filtri.update(m.filtri_dinamici(request, di) or {})
    filtri.update(scelti or {})                          # i filtri scelti sopra il grafico ({percorso: valore})
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


def _aggrega(m, request, periodo, per, aziende, di, scelti=None):
    """(totale, {chiave: [etichetta, valore]}, ordine delle chiavi, vista della prima componente) sommando le componenti."""
    totale, gruppi, ordine, prima = 0, {}, [], None
    for c in m.componenti:
        try:
            vista = interroga.vista_per_nome(c.vista, request)
            r = interroga.aggrega(vista, request, per, c.misura, _filtri(m, c, request, periodo, di, scelti),
                                  con_chiavi=bool(per), aziende=aziende, massimo=None)   # tutti: si taglia dopo
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


def _parametro_lista(vista, chiave, valore):
    """(nome, valore) del parametro della lista per un filtro, o None se la lista non lo sa applicare."""
    if "__" in chiave or isinstance(valore, (list, dict, tuple)) or chiave not in (vista.list_filter or []):
        return None
    if isinstance(valore, bool):
        return f"f_{chiave}", "1" if valore else "0"            # core/viste/filtri.py vuole 1/0 per i booleani
    return f"f_{chiave}", valore


def _url_lista(vista, m, request, periodo, di, extra=None):
    """La lista della vista filtrata come la misura (f_<campo>, f_<data>_da/_a: core/viste/filtri.py), oppure "" se un
    filtro non si può esprimere: un link che mostra altri record sarebbe una bugia."""
    if vista is None:
        return ""
    try:
        base = vista.url("lista")
    except Exception:
        return ""
    parametri = {}
    if m.filtri_lista is not None:
        parametri.update(m.filtri_lista)
    else:
        filtri = dict(m.componenti[0].filtri)
        if m.filtri_dinamici:
            filtri.update(m.filtri_dinamici(request, di) or {})
        for chiave, valore in filtri.items():
            coppia = _parametro_lista(vista, chiave, valore)
            if coppia is None:
                return ""
            parametri[coppia[0]] = coppia[1]
    if periodo is not None and m.periodo_su:
        if m.periodo_su not in (vista.list_filter or []):
            return ""
        parametri[f"f_{m.periodo_su}_da"] = periodo.dal.isoformat()
        parametri[f"f_{m.periodo_su}_a"] = periodo.al.isoformat()
    for chiave, valore in (extra or {}).items():
        campo = chiave[2:].removesuffix("_da").removesuffix("_a")
        if campo not in (vista.list_filter or []):
            return ""
        parametri[chiave] = valore
    return f"{base}?{urlencode(parametri)}" if parametri else base


def _extra_gruppo(per, chiave):
    nome, _, parte = per.partition(":")
    if not parte:
        return {f"f_{nome}": chiave}
    inizio = _data(chiave)
    fine = interroga.avanti_periodo(inizio, parte) - datetime.timedelta(days=1)
    return {f"f_{nome}_da": inizio.isoformat(), f"f_{nome}_a": fine.isoformat()}


def _percorsi_scelti(m, scelti):
    """{percorso: valore} dei filtri scelti sopra il grafico, per nome di raggruppamento (non per data)."""
    percorsi = {}
    for nome, valore in (scelti or {}).items():
        percorso = m.raggruppamenti.get(nome, "")
        if not percorso or ":" in percorso:
            raise ErroreInterrogazione(f"La misura «{m.etichetta}» non si filtra per «{nome}».")
        percorsi[percorso] = valore
    return percorsi


def calcola(nome, request, periodo="", dal=None, al=None, per="", primi=None, confronta="", aziende=None, di="",
            scelti=None):
    """Il valore di una misura con la sua definizione e i link ai record. Vedi il docstring del modulo. `scelti`:
    {raggruppamento: valore} scelti sopra il grafico (cliente, commerciale…), anche nei link."""
    m = per_nome(nome)
    scelti = _percorsi_scelti(m, scelti)
    extra_scelti = {f"f_{k}": v for k, v in scelti.items()}
    if m.permesso and not request.user.has_perm(m.permesso):
        raise ErroreInterrogazione(f"Misura «{m.etichetta}»: non hai il permesso di vedere questi dati.")
    risultato = {"nome": m.nome, "etichetta": m.etichetta, "definizione": m.definizione, "unita": m.unita,
                 "periodo": None, "gruppi": [], "confronto": None, "url": ""}
    try:
        primi = max(1, min(int(primi), MAX_PRIMI)) if primi not in (None, "") else None
    except (TypeError, ValueError):
        raise ErroreInterrogazione("«primi» è un numero intero.")
    ignorati = [n for n, v in (("periodo", periodo or dal or al), ("confronta", confronta)) if v and not m.periodo_su]
    if m.funzione is not None:
        ignorati += [n for n, v in (("per", per), ("aziende", aziende)) if v]
    if ignorati:
        risultato["nota"] = (f"«{m.etichetta}» è la situazione di oggi dell'azienda corrente: {', '.join(ignorati)} "
                             "non si applica. Dillo all'utente se l'aveva chiesto.")
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
    totale, gruppi, ordine, vista = _aggrega(m, request, periodo_scelto, per_campo, aziende, di, scelti)
    risultato["valore"] = totale
    risultato["url"] = _url_lista(vista, m, request, periodo_scelto, di, extra_scelti)
    if risultato["url"] and m.nota_lista:
        risultato["nota_lista"] = m.nota_lista
    if per_campo:
        elenco = [(k, gruppi[k][0], _tondo(gruppi[k][1])) for k in ordine]
        if ":" not in per_campo or primi:
            elenco.sort(key=lambda x: x[2], reverse=True)
        if primi:
            elenco = elenco[:primi]
        risultato["gruppi"] = [{"gruppo": e, "valore": v, "chiave": k,
                                "url": _url_lista(vista, m, request, periodo_scelto, di, {**extra_scelti, **_extra_gruppo(per_campo, k)})
                                if k is not None and risultato["url"] else ""} for k, e, v in elenco]
    if confronta and periodo_scelto is not None:
        p = _confronto(periodo_scelto, confronta, "" if dal or al else (periodo or m.periodo_predefinito))
        precedente, _, _, _ = _aggrega(m, request, p, "", aziende, di, scelti)
        delta = round((totale - precedente) * 100 / abs(precedente), 1) if precedente else None
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


def _scelti(spec, senza=""):
    """{campo: chiave} dei filtri scelti sopra il grafico (spec["scelti"] = {campo: {chiave, etichetta}})."""
    return {k: v["chiave"] for k, v in (spec.get("scelti") or {}).items() if k != senza and isinstance(v, dict)}


def _parametri(spec):
    return {"periodo": spec.get("periodo", ""), "dal": spec.get("dal"), "al": spec.get("al"), "di": spec.get("di", ""),
            "aziende": spec.get("aziende"), "scelti": _scelti(spec)}


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
        link = [g.get("url") or None for g in gruppi[:primi]] + ([None] if len(gruppi) > primi else [])
    else:
        valori, chiavi = [(g["gruppo"], g["valore"]) for g in gruppi], [g.get("chiave") for g in gruppi]
        link = [g.get("url") or None for g in gruppi]
    # il link di ogni gruppo con i filtri della misura (bozze escluse…): il clic sul grafico mostra quei record
    return {"serie": valori, "chiavi": chiavi, "link": link, "totale": r["valore"], "misura": nome, "per": per}


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


# ---------- periodo sul grafico ----------
# I pulsanti sopra un grafico (chat e Analisi): il periodo resta un nome relativo nella specifica, il calcolo lo
# traduce in filtri. Solo dove c'è una data certa: le misure con un periodo e i grafici raggruppati per data.

PULSANTI_PERIODO = (("mese", "Mese"), ("trimestre", "Trimestre"), ("anno", "Anno"), ("anno_scorso", "Anno scorso"))
ETICHETTA_CONFRONTO = "Anno prima"


def _misura_di(spec):
    try:
        return per_nome(spec["misura_aziendale"])
    except ErroreInterrogazione:
        return None


def periodo_grafico(spec):
    """{"scelto", "sempre", "confronta", "pulsanti"} se il grafico ha un periodo da scegliere, altrimenti None.
    «scelto» vuoto: date fisse (misure) o nessun periodo (viste, «Sempre»)."""
    spec = spec or {}
    if spec.get("grafico") == "previsione" or spec.get("tipo") in ("tabella", "kpi"):
        return None
    comuni = {"confronta": bool(spec.get("confronta")), "pulsanti": PULSANTI_PERIODO}
    if spec.get("misura_aziendale"):
        m = _misura_di(spec)
        if m is None or not m.periodo_su or m.funzione is not None:
            return None
        scelto = "" if spec.get("dal") or spec.get("al") else (spec.get("periodo") or m.periodo_predefinito)
        return {"scelto": scelto, "sempre": False, **comuni}
    if ":" in (spec.get("per") or ""):
        return {"scelto": spec.get("periodo") or "", "sempre": True, **comuni}
    return None


def _campo_data(spec):
    return (spec.get("per") or "").partition(":")[0]


class _NonSpostabile(Exception):
    """Un filtro dell'utente sulla data del grafico che non si sa spostare di un anno (es. «__year»)."""


def _filtri_periodo(spec, p, indietro=False):
    """I filtri della specifica con il periodo, in intersezione con i limiti che l'utente ha già messo sulla stessa
    data (da giugno + Anno = da giugno a dicembre). Con `indietro` (il confronto) anche quei limiti tornano indietro
    di un anno; un altro filtro sulla stessa data non si sa spostare: _NonSpostabile."""
    filtri, campo = dict(interroga._decodifica(spec.get("filtri"), "filtri")), _campo_data(spec)
    dal, al = p.dal.isoformat(), p.al.isoformat()
    for chiave in [k for k in filtri if k == campo or k.startswith(f"{campo}__")]:
        valore = filtri[chiave]
        if chiave in (f"{campo}__gte", f"{campo}__lte") and isinstance(valore, str) and len(valore) >= 10:
            if indietro:
                valore = _sposta_mesi(_data(valore), -12).isoformat()
            dal, al = (max(dal, valore[:10]), al) if chiave.endswith("gte") else (dal, min(al, valore[:10]))
            del filtri[chiave]
        elif indietro:
            raise _NonSpostabile
    filtri[f"{campo}__gte"], filtri[f"{campo}__lte"] = dal, al
    return filtri


def _con_scelti(spec):
    """Per i grafici su una vista: i filtri scelti sopra il grafico aggiunti a quelli di Ada (senza toccarli)."""
    if spec.get("misura_aziendale") or not spec.get("scelti"):
        return spec
    return {**spec, "filtri": {**interroga._decodifica(spec.get("filtri"), "filtri"), **_scelti(spec)}}


def spec_per_calcolo(spec):
    """La specifica da calcolare: per i grafici su una vista i filtri scelti si aggiungono a quelli di Ada e il periodo
    diventa un filtro sulla data del raggruppamento (le misure filtri e periodo li applicano da sé)."""
    spec = _con_scelti(spec)
    if spec.get("misura_aziendale") or not spec.get("periodo") or ":" not in (spec.get("per") or ""):
        return spec
    return {**spec, "filtri": _filtri_periodo(spec, risolvi_periodo(spec["periodo"]))}


def spec_anno_prima(spec):
    """La specifica dello stesso periodo un anno prima (per il confronto), o None se il grafico non ha un periodo."""
    # senza «primi»: un cliente fra i primi quest'anno ma non l'anno prima non deve finire nell'«Altro» di allora
    resto = {k: v for k, v in spec.items() if k not in ("periodo", "confronta", "dal", "al", "primi")}
    if spec.get("misura_aziendale"):
        m = _misura_di(spec)
        if m is None or not m.periodo_su:
            return None
        p = risolvi_periodo(spec.get("periodo") or ("" if spec.get("dal") or spec.get("al") else m.periodo_predefinito),
                            spec.get("dal"), spec.get("al"))
        prima = _confronto(p, "anno_prima")
        return {**resto, "dal": prima.dal.isoformat(), "al": prima.al.isoformat()}
    if not spec.get("periodo") or ":" not in (spec.get("per") or ""):
        return None
    try:
        return {**resto, "scelti": {}, "filtri": _filtri_periodo(_con_scelti(spec), _confronto(risolvi_periodo(spec["periodo"]), "anno_prima"), indietro=True)}
    except _NonSpostabile:
        return None


def temporale(spec):
    """Il passo del raggruppamento per data («giorno», «settimana», «mese», «anno»), o "" se non è per data. Per le
    misure decide il raggruppamento dichiarato."""
    per = spec.get("per", "") or ""
    if spec.get("misura_aziendale"):
        m = _misura_di(spec)
        per = m.raggruppamenti.get(per, "") if m else ""
    return per.partition(":")[2]


def _un_anno_dopo(chiave, passo):
    """La chiave dello stesso punto un anno dopo: la stessa settimana ISO per le settimane (i lunedì non cadono
    nello stesso giorno), altrimenti dodici mesi dopo."""
    try:
        data = _data(chiave)
        if passo == "settimana":
            anno, settimana, _ = data.isocalendar()
            return datetime.date.fromisocalendar(anno + 1, settimana, 1).isoformat()
        return _sposta_mesi(data, 12).isoformat()
    except (ErroreInterrogazione, TypeError, ValueError):
        return None


def con_confronto(dati, prima, temporale):
    """I dati con la serie dell'anno prima, allineata ai punti per chiave (sulle date: la chiave di un anno dopo).
    I punti senza un corrispondente valgono 0; «Altro» (chiave None) resta 0."""
    passo = "mese" if temporale is True else (temporale or "")
    valori = {}
    for (_, v), k in zip(prima.get("serie", []), prima.get("chiavi") or []):
        if k is not None:
            valori[_un_anno_dopo(k, passo) if passo else k] = v
    chiavi = dati.get("chiavi") or [None] * len(dati.get("serie", []))
    return {**dati, "confronto": {"etichetta": ETICHETTA_CONFRONTO,
                                  "valori": [valori.get(str(k) if passo else k, 0) if k is not None else 0 for k in chiavi]}}


def scelta_dal_form(dati):
    """(periodo, confronta) dal form dei pulsanti: un pulsante del periodo manda «periodo»; «Confronta» rimanda il
    periodo attuale e inverte il confronto."""
    confronta = dati.get("confronta") == "1"
    if dati.get("inverti") == "1" and "periodo" not in dati:
        return None, not confronta                     # None: il periodo resta quello che è (anche date fisse)
    return dati.get("periodo", dati.get("periodo_attuale", "")), confronta


def titolo_dopo_il_periodo(attuale, vecchia, nuova):
    """Il titolo automatico di una misura («Fatturato dell'anno in corso») segue il periodo scelto; un titolo scritto
    da qualcuno resta com'è."""
    nome = vecchia.get("misura_aziendale")
    try:
        return titolo(nome, nuova) if nome and attuale == titolo(nome, vecchia) else attuale
    except ErroreInterrogazione:
        return attuale


def scegli_periodo(spec, periodo, confronta):
    """La specifica con il periodo scelto dai pulsanti («» = Sempre, solo per i grafici su una vista) e il confronto.
    Un periodo con nome toglie le date fisse. ErroreInterrogazione se il grafico non ha periodo o la scelta non vale."""
    p = periodo_grafico(spec)
    validi = {k for k, _ in PULSANTI_PERIODO} | ({""} if p and p["sempre"] else set())
    if p is None or (periodo is not None and periodo not in validi):
        raise ErroreInterrogazione("Periodo non valido per questo grafico.")
    if periodo is None:                                # solo «Confronta»: il periodo e le date restano
        nuova = {k: v for k, v in spec.items() if k != "confronta"}
    else:
        nuova = {k: v for k, v in spec.items() if k not in ("periodo", "dal", "al", "confronta")}
        if periodo:
            nuova["periodo"] = periodo
    nuova["confronta"] = bool(confronta) and spec_anno_prima(nuova) is not None
    return nuova


def etichetta_periodo(spec):
    """«dell'anno in corso», «del mese in corso, a confronto con l'anno prima», «dal 01/01/2026 al 31/03/2026»: il
    periodo che il grafico mostra, da scrivere accanto al titolo; "" se il grafico non ha un periodo."""
    p = periodo_grafico(spec)
    if p is None:
        return ""
    if spec.get("dal") or spec.get("al"):
        testo = risolvi_periodo("", spec.get("dal"), spec.get("al")).etichetta
    elif p["scelto"]:
        testo = risolvi_periodo(p["scelto"]).etichetta
    else:
        return ""
    return testo + (", a confronto con l'anno prima" if spec.get("confronta") else "")


# ---------- filtri sul grafico ----------
# «Filtra» sopra un grafico: un valore per filtro, salvato in spec["scelti"] separato dai filtri di Ada. Misure: i
# raggruppamenti non per data (cliente, commerciale…); viste: i filtri dell'elenco che non sono date.
MAX_VALORI_FILTRO = 30


def _senza_filtri(spec):
    return spec.get("grafico") == "previsione" or spec.get("tipo") in ("tabella", "kpi")


def _etichetta_campo(vista, percorso, nome):
    try:
        return str(interroga._percorso(vista, percorso, con_operatore=False)[1].verbose_name).capitalize()
    except Exception:
        return nome.replace("__", " ").replace("_", " ").capitalize()


def filtri_grafico(spec, request):
    """[{"campo", "etichetta", "scelto"}] dei filtri che si possono scegliere sopra il grafico."""
    if _senza_filtri(spec):
        return []
    scelti, per = spec.get("scelti") or {}, spec.get("per", "") or ""
    try:
        if spec.get("misura_aziendale"):
            m = per_nome(spec["misura_aziendale"])
            if m.funzione is not None:
                return []
            vista = vista_principale(m.nome, request)
            campi = [(k, percorso) for k, percorso in m.raggruppamenti.items() if ":" not in percorso and k != per]
        else:
            vista = interroga.vista_per_nome(spec.get("vista", ""), request)
            nome_per = per.partition(":")[0]
            campi = []
            for f in vista.list_filter or []:
                campo = interroga._campo_lista(vista, f)
                if campo is not None and f != nome_per and not isinstance(campo, (models.DateField, models.DateTimeField)):
                    campi.append((f, f))
    except ErroreInterrogazione:
        return []
    return [{"campo": k, "etichetta": _etichetta_campo(vista, percorso, k), "scelto": scelti.get(k)} for k, percorso in campi]


def valori_filtro(spec, campo, request):
    """[{"chiave", "etichetta"}] dei valori del filtro presenti nei dati del grafico (con il periodo e gli altri
    filtri scelti), dal più grande; al massimo MAX_VALORI_FILTRO."""
    if campo not in [f["campo"] for f in filtri_grafico(spec, request)]:
        raise ErroreInterrogazione(f"«{campo}» non è un filtro di questo grafico.")
    if spec.get("misura_aziendale"):
        parametri = {**_parametri(spec), "scelti": _scelti(spec, senza=campo)}
        gruppi = calcola(spec["misura_aziendale"], request, per=campo, **parametri)["gruppi"]
        coppie = [(g.get("chiave"), g["gruppo"], g["valore"]) for g in gruppi]
    else:
        altro = spec_per_calcolo({**spec, "scelti": {k: v for k, v in (spec.get("scelti") or {}).items() if k != campo}})
        vista = interroga.vista_per_nome(spec["vista"], request)
        r = interroga.aggrega(vista, request, campo, spec.get("misura", "count") or "count", altro.get("filtri"),
                              spec.get("testo", ""), con_chiavi=True, aziende=interroga.aziende_di(request, spec.get("aziende")))
        coppie = [(g.get("chiave"), g["gruppo"], g["valore"]) for g in r.get("gruppi", [])]
    coppie = sorted((c for c in coppie if c[0] is not None), key=lambda c: c[2] or 0, reverse=True)
    return [{"chiave": k, "etichetta": str(e)} for k, e, _ in coppie[:MAX_VALORI_FILTRO]]


def _come_chiave(testo):
    if testo in ("True", "False"):
        return testo == "True"
    return int(testo) if str(testo).lstrip("-").isdigit() else testo


def scegli_filtro(spec, campo, chiave, etichetta, request):
    """La specifica con il filtro scelto (chiave vuota = toglierlo). ErroreInterrogazione se non è un filtro del grafico."""
    if campo not in [f["campo"] for f in filtri_grafico(spec, request)]:
        raise ErroreInterrogazione(f"«{campo}» non è un filtro di questo grafico.")
    scelti = {k: v for k, v in (spec.get("scelti") or {}).items() if k != campo}
    if chiave not in ("", None):
        scelti[campo] = {"chiave": _come_chiave(chiave), "etichetta": str(etichetta or chiave)[:120]}
    nuova = {k: v for k, v in spec.items() if k != "scelti"}
    if scelti:
        nuova["scelti"] = scelti
    return nuova


def etichetta_filtri(spec):
    """«Cliente: Rossi Srl · Commerciale: Anna»: i filtri scelti, da scrivere accanto al titolo."""
    return " · ".join(f"{k.replace('__', ' ').replace('_', ' ').capitalize()}: {v.get('etichetta', v.get('chiave'))}"
                      for k, v in (spec.get("scelti") or {}).items() if isinstance(v, dict))
