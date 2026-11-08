"""Interrogazioni dichiarative sulle ModelView: filtri, ricerca libera e aggregazioni (conteggi, somme, medie) per
campo, relazione o data, con i permessi e l'azienda della richiesta. È il motore comune dei grafici: lo usano
l'assistente (gli strumenti di lettura e gli artifact), il modulo Analisi e chi vuole un numero di sintesi senza
scrivere una query. Una specifica è un dizionario:

    {"vista": "vendite.ordini", "per": "data:mese" | "cliente" | "", "misura": "count" | "sum:totale" | "avg:...",
     "filtri": {"stato": "confermato", "data__gte": "2026-01-01"}, "testo": "ricerca libera",
     "lista": {"f_stato": "aperta", "q": "..."}}      # i parametri f_* della lista, come li scrive il browser

Il codice valida vista, campi, operatori e permessi a ogni chiamata: la specifica può arrivare da un modello
linguistico o da un form, i dati li calcola sempre il database per l'utente che chiede."""
import datetime
import json
import re
from decimal import Decimal

from django.core.exceptions import FieldDoesNotExist, FieldError, ValidationError
from django.db import models
from django.db.models import Avg, Count, F, Max, Min, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek, TruncYear
from django.http import HttpRequest
from django.utils import timezone

from . import registry
from .gruppi import MESI

ESCLUSE = {"ai"}                                         # le viste dell'assistente (provider, chiavi...) mai
SENSIBILE = re.compile(r"password|chiave|token|segret|secret|cifrat|hash", re.IGNORECASE)
OPERATORI = {"exact", "iexact", "icontains", "istartswith", "in", "gt", "gte", "lt", "lte", "isnull", "year",
             "month"}
GRUPPI_MASSIMI = 100
MAX_CATEGORIE = 30
AGGREGATI = {"sum": Sum, "avg": Avg, "min": Min, "max": Max}
TRONCATURE = {"giorno": TruncDay, "settimana": TruncWeek, "mese": TruncMonth, "anno": TruncYear}
SOLO_DATA = re.compile(r"\d{4}-\d{2}-\d{2}")


class ErroreInterrogazione(Exception):
    """Errore previsto (specifica sbagliata, vista o campo inesistenti, valore non valido): il messaggio è per chi
    ha scritto la specifica, persona o modello, senza traceback."""


# ---------- viste ----------

def id_vista(vista):
    return f"{vista.modulo}.{vista.slug}"


def viste_accessibili(request, modulo="", escluse=ESCLUSE):
    """Le viste che l'utente della richiesta può vedere (personalizzate per lui), in ordine stabile; `modulo` le
    limita a un'app."""
    from django.conf import settings

    from core.registry.modules import disattivati
    registry.autodiscover(["core", *settings.ADDONS_ATTIVI])
    spenti = disattivati()
    risultato = []
    for m in ["core", *settings.ADDONS_ATTIVI]:
        if m in escluse or m in spenti or (modulo and m != modulo):
            continue
        for v in registry.viste_di(m):
            v = v.personalizzata(request)
            if v.has_view_permission(request):
                risultato.append(v)
    return risultato


def vista_per_nome(nome, request, **limiti):
    for v in viste_accessibili(request, **limiti):
        if id_vista(v) == nome:
            return v
    raise ErroreInterrogazione(f"Vista «{nome}» inesistente o non accessibile.")


def richiesta_di(utente, azienda=None):
    """Una richiesta minima per usare le ModelView fuori dal browser (worker, cache): stesso utente, stessa azienda."""
    from django.conf import settings
    host = next((h for h in settings.ALLOWED_HOSTS if h and h != "*" and not h.startswith(".")), "localhost")
    request = HttpRequest()
    request.method = "GET"
    request.user, request.azienda = utente, azienda
    request.META.update({"HTTP_HOST": host, "SERVER_NAME": host, "SERVER_PORT": "80"})
    request.session = {}
    if azienda is None and getattr(utente, "is_authenticated", False):
        from core.azienda import corrente
        request.azienda = corrente(request)
    return request


# ---------- campi ----------

def _sensibile(campo):
    return bool(SENSIBILE.search(campo.name))


def campi_leggibili(vista, request=None):
    """I campi del modello che si possono leggere e interrogare: concreti e M2M, tranne quelli sensibili, quelli
    interni (non modificabili e non mostrati dalla vista) e quelli nascosti per il ruolo di chi chiede."""
    mostrati = set(vista.readonly_fields) | set(vista.list_display)
    nascosti = set()
    if request is not None:
        from core import regole
        nascosti = regole.nascosti(vista, request)
    campi = []
    for f in vista.opts.get_fields():
        if f.auto_created and not f.concrete:
            continue
        if not (f.concrete or f.many_to_many) or _sensibile(f) or f.name == "proprieta":
            continue
        if not f.primary_key and not getattr(f, "editable", True) and f.name not in mostrati:
            continue
        if f.name in nascosti:
            continue
        campi.append(f)
    return campi


def _campo(modello, nome):
    try:
        f = modello._meta.get_field(nome)
    except FieldDoesNotExist:
        return None
    if _sensibile(f) or not (f.concrete or f.many_to_many):
        return None
    return f


def _percorso(vista, chiave, con_operatore=True):
    """'cliente__nome__icontains' → (lookup Django, campo finale, operatore). Al massimo un salto su una relazione."""
    parti = chiave.split("__")
    operatore = parti.pop() if con_operatore and len(parti) > 1 and parti[-1] in OPERATORI else ""
    if not 1 <= len(parti) <= 2:
        raise ErroreInterrogazione(f"Campo «{chiave}» non valido: al massimo un salto su una relazione (es. cliente__nome).")
    f = _campo(vista.model, parti[0])
    if f is None:
        raise ErroreInterrogazione(f"La vista non ha il campo «{parti[0]}».")
    if len(parti) == 2:
        if not f.is_relation:
            raise ErroreInterrogazione(f"«{parti[0]}» non è una relazione.")
        f = _campo(f.related_model, parti[1])
        if f is None:
            raise ErroreInterrogazione(f"«{parti[0]}» non ha il campo «{parti[1]}».")
    return "__".join(parti), f, operatore


def _decodifica(valore, nome):
    if isinstance(valore, str):
        try:
            valore = json.loads(valore) if valore.strip() else {}
        except ValueError:
            raise ErroreInterrogazione(f"«{nome}» deve essere un oggetto JSON.")
    return valore or {}


def controlla_nascosti(vista, request, *nomi):
    """Un campo nascosto per il ruolo di chi chiede non si filtra, non si raggruppa e non si somma: altrimenti lo si
    ricostruirebbe dai risultati."""
    from core import regole
    via = regole.nascosti(vista, request)
    for nome in nomi:
        testo = str(nome or "")
        if ":" in testo and testo.split(":", 1)[0] in AGGREGATI:      # sum:totale → totale
            testo = testo.split(":", 1)[1]
        radice = testo.split(":", 1)[0].split("__", 1)[0]               # data:mese → data, cliente__nome → cliente
        if radice and radice in via:
            raise ErroreInterrogazione(f"Il campo «{radice}» non è disponibile per il tuo ruolo.")


def filtra(vista, request, qs, testo="", filtri=None, lista=None):
    """Ricerca libera sui search_fields della vista, filtri {campo[__operatore]: valore} e, se ci sono, i parametri
    della lista (q, f_*) come li manda il browser."""
    testo = (testo or "").strip()
    if testo:
        if not vista.search_fields:
            raise ErroreInterrogazione("Questa vista non ha la ricerca libera: usa i filtri.")
        q = Q()
        for c in vista.search_fields:
            q |= Q(**{f"{c}__icontains": testo})
        qs = qs.filter(q)
    distinti = False
    for chiave, valore in _decodifica(filtri, "filtri").items():
        controlla_nascosti(vista, request, chiave)
        lookup, f, operatore = _percorso(vista, chiave)
        if operatore == "in" and not isinstance(valore, list):
            raise ErroreInterrogazione(f"Il filtro «{chiave}» vuole una lista di valori.")
        if isinstance(f, models.DateTimeField) and operatore in ("", "exact", "gt", "gte", "lt", "lte") \
                and isinstance(valore, str) and SOLO_DATA.fullmatch(valore.strip()):
            lookup = f"{lookup}__date"                    # «2026-07-01» su data e ora: il giorno, nel fuso locale
        try:
            qs = qs.filter(**{f"{lookup}__{operatore}" if operatore else lookup: valore})
        except (ValueError, TypeError, ValidationError) as e:
            raise ErroreInterrogazione(f"Valore non valido per «{chiave}»: {e}")
        except FieldError:
            raise ErroreInterrogazione(
                f"L'operatore «{operatore}» non vale per «{chiave}»"
                + (f": è un collegamento a un altro record, filtra per id o per un suo campo (es. «{lookup}__id» o «{lookup}__<campo>__icontains»)."
                   if f.is_relation else "."))
        distinti = distinti or f.many_to_many or "__" in lookup
    if lista:
        from .filtri import applica
        try:
            qs = applica(vista, request, qs, parametri={k: v for k, v in dict(lista).items() if k != "o"})
        except (ValueError, TypeError, ValidationError) as e:
            raise ErroreInterrogazione(f"Filtri della lista non validi: {e}")
    return qs.distinct() if distinti else qs


# ---------- aggregazioni ----------

def _etichette_gruppi(f, parte, valori):
    if f.is_relation:
        oggetti = f.related_model._default_manager.in_bulk([v for v in valori if v is not None])
        return {v: str(oggetti.get(v, v)) if v is not None else "—" for v in valori}
    mappa = {k: str(e) for k, e in f.flatchoices} if f.choices else {}
    risultato = {}
    for v in valori:
        if v is None or v == "":
            risultato[v] = "—"
        elif parte == "mese":
            risultato[v] = f"{MESI[v.month - 1]} {v.year}"
        elif parte == "anno":
            risultato[v] = str(v.year)
        elif parte == "settimana":
            risultato[v] = f"sett. {v:%d/%m/%y}"
        elif parte == "giorno":
            risultato[v] = (v.date() if isinstance(v, datetime.datetime) else v).isoformat()
        elif isinstance(v, bool):
            risultato[v] = "sì" if v else "no"
        else:
            risultato[v] = mappa.get(v, str(v))
    return risultato


def _misura(vista, misura):
    """'count' | 'sum:campo' | 'avg:campo' | 'min:campo' | 'max:campo' → (espressione, campo o None)."""
    if misura in ("", "count"):
        return Count("pk", distinct=True), None
    funzione, _, nome = misura.partition(":")
    if funzione not in AGGREGATI or not nome:
        raise ErroreInterrogazione("«misura» è count oppure sum:, avg:, min:, max: seguiti da un campo numerico.")
    lookup, f, _ = _percorso(vista, nome, con_operatore=False)
    numerico = isinstance(f, (models.IntegerField, models.DecimalField, models.FloatField))
    if not numerico and not (funzione in ("min", "max") and isinstance(f, models.DateField)):
        raise ErroreInterrogazione(f"«{nome}» non è un campo numerico.")
    return AGGREGATI[funzione](lookup), f


def _numero(v, f):
    if v is None:
        return 0
    if isinstance(v, Decimal):
        return int(v) if isinstance(f, models.IntegerField) else float(round(v, 2))
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def etichetta_misura(vista, misura):
    """«Numero», «Somma di totale», «Media di ore»…"""
    funzione, _, nome = (misura or "count").partition(":")
    if funzione == "count":
        return "Numero"
    try:
        _, f, _ = _percorso(vista, nome, con_operatore=False)
        nome = str(f.verbose_name).lower()
    except ErroreInterrogazione:
        pass
    return {"sum": "Somma di", "avg": "Media di", "min": "Minimo di", "max": "Massimo di"}.get(funzione, funzione) + f" {nome}"


def _chiave(v):
    """Il valore grezzo di un gruppo in forma serializzabile (pk, codice della scelta, data ISO)."""
    if isinstance(v, datetime.datetime):
        v = timezone.localtime(v) if timezone.is_aware(v) else v
        return v.date().isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


# ---------- più aziende insieme (consolidato) ----------

def aziende_di(request, valore):
    """Le aziende da consolidare: "tutte" (quelle dell'utente) o una lista di id tra le sue; None = solo la corrente."""
    if not valore:
        return None
    from core.azienda import consentite
    tutte = consentite(request.user)
    if valore == "tutte":
        scelte = list(tutte)
    else:
        ids = {int(x) for x in (valore if isinstance(valore, (list, tuple)) else str(valore).split(",")) if str(x).strip().isdigit()}
        scelte = [a for a in tutte if a.pk in ids]
    return scelte or None


def _ordina_chiavi(chiavi):
    try:
        return sorted(chiavi, key=lambda k: (k is None, k))
    except TypeError:
        return chiavi


def _unisci(valori, funzione):
    valori = [v for v in valori if v is not None]
    if not valori:
        return 0
    if funzione == "min":
        return min(valori)
    if funzione == "max":
        return max(valori)
    return round(sum(valori), 2) if any(isinstance(v, float) for v in valori) else sum(valori)


def _aggrega_aziende(vista, request, aziende, per, misura, filtri, testo, lista, con_chiavi):
    """Ogni azienda con le sue regole (la vista e il suo queryset, come se l'utente ci lavorasse), poi si sommano i
    gruppi con la stessa chiave; le medie vengono da somme e conteggi, così restano giuste."""
    funzione, _, campo = (misura or "count").partition(":")
    if funzione == "avg":
        somme = _aggrega_aziende(vista, request, aziende, per, f"sum:{campo}", filtri, testo, lista, True)
        conti = _aggrega_aziende(vista, request, aziende, per, "count", filtri, testo, lista, True)
        n = {g.get("chiave"): g["valore"] for g in conti.get("gruppi", [])}
        gruppi = [{**g, "valore": round(g["valore"] / n[g.get("chiave")], 2) if n.get(g.get("chiave")) else 0}
                  for g in somme.get("gruppi", [])]
        risultato = {**somme, "misura": misura, "totale": round(somme["totale"] / conti["totale"], 2) if conti["totale"] else 0}
        if per:
            risultato["gruppi"] = gruppi if con_chiavi else [{k: v for k, v in g.items() if k != "chiave"} for g in gruppi]
        return risultato
    parziali = [aggrega(vista, richiesta_di(request.user, a), per, misura, filtri, testo, lista, con_chiavi=True) for a in aziende]
    risultato = {"vista": id_vista(vista), "misura": misura or "count", "totale": _unisci([r["totale"] for r in parziali], funzione),
                 "aziende": [str(a) for a in aziende]}
    if not per:
        return risultato
    valori, etichette = {}, {}
    for r in parziali:
        for g in r.get("gruppi", []):
            chiave = g.get("chiave")
            valori.setdefault(chiave, []).append(g["valore"])
            etichette.setdefault(chiave, g["gruppo"])
    gruppi = [{"gruppo": etichette[k], "valore": _unisci(valori[k], funzione), **({"chiave": k} if con_chiavi else {})}
              for k in _ordina_chiavi(list(valori))]
    risultato.update(per=per, gruppi=gruppi[:GRUPPI_MASSIMI])
    if len(gruppi) > GRUPPI_MASSIMI or any(r.get("nota") for r in parziali):
        risultato["nota"] = f"Più di {GRUPPI_MASSIMI} gruppi: mostrati i primi. Restringi i filtri."
    return risultato


def aggrega(vista, request, per="", misura="count", filtri=None, testo="", lista=None, con_chiavi=False, aziende=None):
    """{"misura", "per", "gruppi": [{"gruppo", "valore"[, "chiave"]}], "totale"} con i dati aggregati nel database;
    con `con_chiavi` ogni gruppo porta anche il valore grezzo, per aprire la lista filtrata su quel gruppo.
    Con `aziende` (vedi aziende_di) il consolidato di più aziende."""
    controlla_nascosti(vista, request, per, misura)
    if aziende:
        return _aggrega_aziende(vista, request, aziende, per, misura, filtri, testo, lista, con_chiavi)
    espressione, f_misura = _misura(vista, misura or "count")
    qs = filtra(vista, request, vista.get_queryset(request), testo, filtri, lista).order_by()
    if qs.query.distinct:                     # filtro su una relazione multipla: senza doppioni nelle somme
        qs = vista.model._default_manager.filter(pk__in=qs.values("pk"))
    totale = _numero(qs.aggregate(_v=espressione)["_v"], f_misura)
    risultato = {"vista": id_vista(vista), "misura": misura or "count", "totale": totale}
    if not per:
        return risultato
    nome, _, parte = per.partition(":")
    lookup, f, _ = _percorso(vista, nome, con_operatore=False)
    if parte:
        if parte not in TRONCATURE or not isinstance(f, (models.DateField, models.DateTimeField)):
            raise ErroreInterrogazione("«per» con :giorno, :settimana, :mese o :anno vale solo per i campi data.")
        chiave = TRONCATURE[parte](lookup)
    elif isinstance(f, models.DateTimeField):
        raise ErroreInterrogazione(f"Raggruppa «{nome}» per :giorno, :settimana, :mese o :anno.")
    elif isinstance(f, models.TextField):
        raise ErroreInterrogazione("Non si raggruppa per un testo lungo.")
    else:
        chiave = F(lookup)
    righe = list(qs.annotate(_g=chiave).values("_g").annotate(_v=espressione).order_by("_g")[:GRUPPI_MASSIMI + 1])
    etichette = _etichette_gruppi(f, parte, [r["_g"] for r in righe])
    gruppi = [{"gruppo": etichette[r["_g"]], "valore": _numero(r["_v"], f_misura)} for r in righe[:GRUPPI_MASSIMI]]
    if con_chiavi:
        for g, r in zip(gruppi, righe):
            g["chiave"] = _chiave(r["_g"])
    risultato.update(per=per, gruppi=gruppi)
    if len(righe) > GRUPPI_MASSIMI:
        risultato["nota"] = f"Più di {GRUPPI_MASSIMI} gruppi: mostrati i primi. Restringi i filtri."
    return risultato


def serie(gruppi, per, massimo=MAX_CATEGORIE):
    """[(etichetta, valore)] da disegnare: oltre `massimo` categorie le prime per valore più «Altro» (per le date:
    le ultime, in ordine di tempo)."""
    coppie = [(g["gruppo"], g["valore"]) for g in gruppi]
    if len(coppie) <= massimo:
        return coppie
    if ":" in per:
        return coppie[-massimo:]
    ordinate = sorted(coppie, key=lambda c: c[1], reverse=True)
    return ordinate[:massimo - 1] + [("Altro", round(sum(v for _, v in ordinate[massimo - 1:]), 2))]


def serie_con_chiavi(gruppi, per, massimo=MAX_CATEGORIE, ordine=""):
    """([(etichetta, valore)], [chiave o None]) da disegnare: come serie(), più la chiave grezza di ogni punto
    («Altro» non ne ha); con ordine="valore" le categorie vanno dalla più grande (le date restano in ordine di tempo)."""
    terne = [(g["gruppo"], g["valore"], g.get("chiave")) for g in gruppi]
    temporale = ":" in per
    if temporale:
        terne = [t for t in terne if t[2] is not None]   # i record senza data non hanno un posto sulla linea del tempo
    if len(terne) > massimo:
        if temporale:
            terne = terne[-massimo:]
        else:
            ordinate = sorted(terne, key=lambda t: t[1], reverse=True)
            terne = ordinate[:massimo - 1] + [("Altro", round(sum(v for _, v, _ in ordinate[massimo - 1:]), 2), None)]
    if ordine == "valore" and not temporale:
        terne.sort(key=lambda t: (t[0] == "Altro", -t[1]))
    return [(e, v) for e, v, _ in terne], [k for _, _, k in terne]


def calcola(spec, request):
    """La serie di una specifica di grafico: {"serie": [(etichetta, valore)], "chiavi", "totale", "misura", "per"}."""
    vista = vista_per_nome(spec["vista"], request)
    per = spec.get("per", "") or ""
    if not per:
        raise ErroreInterrogazione("Un grafico ha bisogno di «per»: un campo o una data (data:mese, data:anno…).")
    r = aggrega(vista, request, per, spec.get("misura", "count"), spec.get("filtri"), spec.get("testo", ""),
                spec.get("lista"), con_chiavi=True, aziende=aziende_di(request, spec.get("aziende")))
    valori, chiavi = serie_con_chiavi(r.get("gruppi", []), per, int(spec.get("massimo") or MAX_CATEGORIE), spec.get("ordine", ""))
    return {"serie": valori, "chiavi": chiavi, "totale": r["totale"], "misura": r["misura"], "per": per}


# ---------- periodi e KPI ----------

PERIODI = {"giorno": TruncDay, "settimana": TruncWeek, "mese": TruncMonth, "anno": TruncYear}
MESI_BREVI = [m[:3] for m in MESI]


def inizio_periodo(data, periodo):
    if periodo == "anno":
        return data.replace(month=1, day=1)
    if periodo == "mese":
        return data.replace(day=1)
    if periodo == "settimana":
        return data - datetime.timedelta(days=data.weekday())
    return data


def avanti_periodo(data, periodo, passi=1):
    if periodo == "anno":
        return data.replace(year=data.year + passi)
    if periodo == "mese":
        mese = data.month - 1 + passi
        return data.replace(year=data.year + mese // 12, month=mese % 12 + 1, day=1)
    return data + datetime.timedelta(days=passi * (7 if periodo == "settimana" else 1))


def etichetta_periodo(data, periodo):
    if periodo == "anno":
        return str(data.year)
    if periodo == "mese":
        return f"{MESI_BREVI[data.month - 1]} {data.year}"
    if periodo == "settimana":
        return f"sett. {data:%d/%m}"
    return f"{data:%d/%m}"


NOMI_PERIODO = {"giorno": ("oggi", "ieri"), "settimana": ("questa settimana", "la settimana scorsa"),
                "mese": ("questo mese", "il mese scorso"), "anno": ("quest'anno", "l'anno scorso")}


def _come_data(valore):
    if isinstance(valore, datetime.datetime):
        return timezone.localtime(valore).date() if timezone.is_aware(valore) else valore.date()
    return valore


def kpi(spec, request, storia=12):
    """Il numero di un KPI: la misura nel periodo in corso, quella del periodo prima (per il delta %) e gli ultimi
    `storia` periodi (per la sparkline), sul campo data della specifica; senza campo data, solo il totale.
    {"valore", "precedente", "delta", "storico": [(etichetta, valore)], "periodo", "unita"}
    Con spec["aziende"] il consolidato di più aziende (somme e conteggi sommati, medie da somma e conteggio)."""
    aziende = aziende_di(request, spec.get("aziende"))
    if aziende:
        return _kpi_aziende(spec, request, aziende, storia)
    vista = vista_per_nome(spec["vista"], request)
    misura = spec.get("misura", "count") or "count"
    espressione, f_misura = _misura(vista, misura)
    unita = "€" if f_misura is not None and "€" in str(f_misura.verbose_name) else ""
    qs = filtra(vista, request, vista.get_queryset(request), spec.get("testo", ""), spec.get("filtri"), spec.get("lista")).order_by()
    if qs.query.distinct:
        qs = vista.model._default_manager.filter(pk__in=qs.values("pk"))
    data = spec.get("data", "") or ""
    if not data:
        return {"valore": _numero(qs.aggregate(_v=espressione)["_v"], f_misura), "precedente": None, "delta": None,
                "storico": [], "periodo": "", "unita": unita}
    periodo = spec.get("periodo", "mese") or "mese"
    if periodo not in PERIODI:
        raise ErroreInterrogazione("«periodo» è giorno, settimana, mese o anno.")
    lookup, f, _ = _percorso(vista, data, con_operatore=False)
    if not isinstance(f, (models.DateField, models.DateTimeField)):
        raise ErroreInterrogazione(f"«{data}» non è un campo data.")
    attuale = inizio_periodo(timezone.localdate(), periodo)
    primo = avanti_periodo(attuale, periodo, -(storia - 1))
    campo = f"{lookup}__date" if isinstance(f, models.DateTimeField) else lookup
    righe = qs.filter(**{f"{campo}__gte": primo}).annotate(_p=PERIODI[periodo](lookup)).values("_p").annotate(_v=espressione).order_by("_p")
    valori = {_come_data(r["_p"]): _numero(r["_v"], f_misura) for r in righe if r["_p"] is not None}
    periodi = [avanti_periodo(primo, periodo, i) for i in range(storia)]
    valore, precedente = valori.get(attuale, 0), valori.get(avanti_periodo(attuale, periodo, -1), 0)
    delta = round((valore - precedente) * 100 / precedente, 1) if precedente else None
    return {"valore": valore, "precedente": precedente, "delta": delta, "periodo": periodo, "unita": unita,
            "storico": [(etichetta_periodo(p, periodo), valori.get(p, 0)) for p in periodi]}


def _kpi_aziende(spec, request, aziende, storia):
    base = {k: v for k, v in spec.items() if k != "aziende"}
    funzione, _, campo = (spec.get("misura") or "count").partition(":")
    if funzione == "avg":
        s = _kpi_aziende({**base, "misura": f"sum:{campo}"}, request, aziende, storia)
        c = _kpi_aziende({**base, "misura": "count"}, request, aziende, storia)
        dividi = lambda a, b: round(a / b, 2) if b else 0          # noqa: E731
        valore, precedente = dividi(s["valore"], c["valore"]), dividi(s["precedente"] or 0, c["precedente"] or 0)
        return {**s, "valore": valore, "precedente": precedente if s["precedente"] is not None else None,
                "delta": round((valore - precedente) * 100 / precedente, 1) if precedente else None,
                "storico": [(e, dividi(v, c["storico"][i][1])) for i, (e, v) in enumerate(s["storico"])]}
    parziali = [kpi(base, richiesta_di(request.user, a), storia) for a in aziende]
    primo = parziali[0]
    valore = _unisci([p["valore"] for p in parziali], funzione)
    precedente = None if primo["precedente"] is None else _unisci([p["precedente"] for p in parziali], funzione)
    storico = [(e, _unisci([p["storico"][i][1] for p in parziali], funzione)) for i, (e, _) in enumerate(primo["storico"])]
    return {**primo, "valore": valore, "precedente": precedente, "storico": storico, "aziende": [str(a) for a in aziende],
            "delta": round((valore - precedente) * 100 / precedente, 1) if precedente else None}


# ---------- per il costruttore ----------

def opzioni_vista(vista):
    """Che cosa si può chiedere a una vista: {"misure": [(valore, etichetta)], "raggruppamenti": [...], "date": [...]}
    dai campi leggibili; prima quelli che la vista stessa suggerisce (list_sum, list_group_by)."""
    campi = [f for f in campi_leggibili(vista) if not f.primary_key]
    misure = [("count", "Numero di record")]
    numerici = [f for f in campi if isinstance(f, (models.IntegerField, models.DecimalField, models.FloatField))
                and not isinstance(f, models.AutoField) and not f.is_relation]
    posizione_somme = {c: i for i, c in enumerate(vista.list_sum)}
    numerici.sort(key=lambda f: (posizione_somme.get(f.name, len(posizione_somme)), str(f.verbose_name).lower()))
    for f in numerici:
        nome = str(f.verbose_name)
        misure += [(f"sum:{f.name}", f"Somma di {nome}"), (f"avg:{f.name}", f"Media di {nome}")]
    raggruppamenti, date = [], []
    for f in campi:
        nome = str(f.verbose_name)
        if f.many_to_many or isinstance(f, (models.TextField, models.JSONField, models.FileField)):
            continue
        if isinstance(f, (models.DateField, models.DateTimeField)):
            date.append((f.name, nome))
            raggruppamenti += [(f"{f.name}:mese", f"{nome} (mese)"), (f"{f.name}:settimana", f"{nome} (settimana)"),
                               (f"{f.name}:anno", f"{nome} (anno)"), (f"{f.name}:giorno", f"{nome} (giorno)")]
        elif isinstance(f, (models.DecimalField, models.FloatField)):
            continue                                     # non si raggruppa per un importo
        elif f.is_relation or f.choices or isinstance(f, (models.BooleanField, models.CharField, models.IntegerField)):
            raggruppamenti.append((f.name, nome))
    posizione = {c: i for i, c in enumerate(vista.list_group_by)}     # prima quelli della vista, nel suo ordine
    raggruppamenti.sort(key=lambda c: (posizione.get(c[0], len(posizione)), c[1].lower()))
    return {"misure": misure, "raggruppamenti": raggruppamenti, "date": date}
