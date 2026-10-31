"""Server MCP per Agate: gli strumenti ammessi dell'assistente AI, eseguiti a nome degli agenti.

Un'azione di un agente arriva qui solo come chiamata MCP fatta **da Agate**, dopo che le sue regole (e, se serve,
una persona) l'hanno decisa: per questo la decisione di Agate sostituisce la conferma in chat. Le scritture non
diventano una `Proposta`: si esegue l'anteprima (che valida con gli stessi form del browser) e poi l'operazione, in
una transazione, con l'utente agente e l'azienda degli agenti.

Trasporto: MCP "streamable HTTP" nella forma più semplice, come il server di Agate: una richiesta JSON-RPC per
POST, una risposta JSON, nessun flusso SSE né sessione. Metodi: `initialize`, `ping`, `tools/list`, `tools/call`;
le notifiche (`notifications/initialized`) ricevono 202 senza corpo.

Autenticazione: `Authorization: Bearer awf_...`, il bearer generato al collegamento; se ne tiene solo l'impronta,
confrontata a tempo costante.

Risposte di `tools/call`: `{"content": [{"type": "text", ...}], "structuredContent": {...}, "isError": bool}`.
Gli errori nominano il parametro e il problema, mai i valori."""
import json
import logging

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import agenti, fabbrica, operazioni, osservazione
from .models import Chiamata, Collegamento

log = logging.getLogger("awf.mcp")

VERSIONI_PROTOCOLLO = ("2025-11-25", "2025-06-18", "2025-03-26")
MAX_CORPO = 1_000_000
CHIAVI_AGENTE_META = ("agentlia/agent", "agent")
ARGOMENTI_AGENTE = ("agente", "agent")
ISTRUZIONI = ("Operazioni del gestionale adabox, esposte ad Agate per gli agenti di Agentic Workforce. Ogni "
              "strumento dichiara il suo effetto: lettura, scrittura o operazione irreversibile. Le viste ammesse "
              "sono quelle elencate nello schema.")
PARSE, RICHIESTA_NON_VALIDA, METODO_SCONOSCIUTO, PARAMETRI_NON_VALIDI = -32700, -32600, -32601, -32602
TIPI_JSON = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


class ErroreRpc(Exception):
    def __init__(self, codice, messaggio):
        super().__init__(messaggio)
        self.codice, self.messaggio = codice, messaggio


# ---------- vista HTTP ----------

@csrf_exempt
def mcp(request):
    if request.method != "POST":
        risposta = JsonResponse({"error": "usare POST (una richiesta JSON-RPC)"}, status=405)
        risposta["Allow"] = "POST"
        return risposta
    if not autorizzato(request):
        risposta = JsonResponse({"error": "bearer mancante o non valido"}, status=401)
        risposta["WWW-Authenticate"] = 'Bearer realm="awf"'
        return risposta
    try:
        dimensione = int(request.headers.get("Content-Length") or 0)
    except ValueError:
        dimensione = 0
    if dimensione > MAX_CORPO:
        return JsonResponse(_errore(None, RICHIESTA_NON_VALIDA, "richiesta troppo grande"), status=413)
    try:
        messaggio = json.loads(request.body)
    except ValueError:
        return JsonResponse(_errore(None, PARSE, "JSON non valido"), status=400)
    risposta = gestisci(messaggio)
    if risposta is None:
        return HttpResponse(status=202)
    return JsonResponse(risposta)


def autorizzato(request):
    schema, _, token = (request.headers.get("Authorization") or "").partition(" ")
    c = Collegamento.objects.filter(pk=1).only("mcp_impronta").first()
    salvata = c.mcp_impronta if c is not None else ""
    valido = fabbrica.bearer_valido(token.strip(), salvata)       # lo stesso lavoro anche senza bearer
    return schema.lower() == "bearer" and bool(token.strip()) and valido


# ---------- JSON-RPC ----------

def gestisci(messaggio):
    """Una richiesta JSON-RPC → la risposta; None per le notifiche."""
    if not isinstance(messaggio, dict) or messaggio.get("jsonrpc") != "2.0":
        return _errore(None, RICHIESTA_NON_VALIDA, "richiesta JSON-RPC 2.0 non valida")
    if "id" not in messaggio:                           # notifica: notifications/initialized, cancelled...
        return None
    ident, metodo, parametri = messaggio.get("id"), messaggio.get("method"), messaggio.get("params") or {}
    try:
        if not isinstance(metodo, str) or not isinstance(parametri, dict):
            raise ErroreRpc(RICHIESTA_NON_VALIDA, "metodo o parametri non validi")
        if metodo == "initialize":
            risultato = _inizializza(parametri)
        elif metodo == "ping":
            risultato = {}
        elif metodo == "tools/list":
            risultato = {"tools": [e.strumento_mcp() for e in operazioni.esposte()]}
        elif metodo == "tools/call":
            nome, argomenti = parametri.get("name"), parametri.get("arguments") or {}
            meta = parametri.get("_meta") if isinstance(parametri.get("_meta"), dict) else {}
            if not isinstance(nome, str) or not isinstance(argomenti, dict):
                raise ErroreRpc(PARAMETRI_NON_VALIDI, "servono name e arguments")
            risultato = chiama(nome, argomenti, meta)
        else:
            raise ErroreRpc(METODO_SCONOSCIUTO, "metodo non supportato")
    except ErroreRpc as e:
        return _errore(ident, e.codice, e.messaggio)
    return {"jsonrpc": "2.0", "id": ident, "result": risultato}


def _inizializza(parametri):
    from core.registry.modules import manifests_attivi
    chiesta = str(parametri.get("protocolVersion") or "")
    manifest = manifests_attivi().get("awf")
    return {"protocolVersion": chiesta if chiesta in VERSIONI_PROTOCOLLO else VERSIONI_PROTOCOLLO[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "adabox-awf", "title": "adabox · Agentic Workforce",
                           "version": manifest.version if manifest else "1.0.0"},
            "instructions": ISTRUZIONI}


def _errore(ident, codice, messaggio):
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": codice, "message": messaggio}}


def _risultato(testo, dati, errore=False):
    return {"content": [{"type": "text", "text": testo}], "structuredContent": dati, "isError": errore}


# ---------- tools/call ----------

def _valori(x):
    """I valori testuali degli argomenti (a ogni profondità), per toglierli dai messaggi di errore."""
    if isinstance(x, dict):
        return [v for y in x.values() for v in _valori(y)]
    if isinstance(x, list):
        return [v for y in x for v in _valori(y)]
    return [x] if isinstance(x, str) and len(x) >= 3 else []


def _senza_valori(testo, argomenti):
    """Il messaggio di errore senza i valori passati dall'agente (possono essere dati personali)."""
    testo = str(testo)
    for v in sorted(set(_valori(argomenti)), key=len, reverse=True):
        testo = testo.replace(v, "…")
    return testo[:500]


def _nome_parametro(chiave):
    pulito = "".join(c for c in str(chiave) if c.isalnum() or c == "_")[:64]
    return pulito or "?"


def _agente_indicato(argomenti, meta, schema):
    """Il nome dell'agente scritto nella chiamata; toglie `agente`/`agent` dagli argomenti se non sono parametri
    dello strumento. Prima `_meta` (lo mette Agate), poi l'argomento."""
    proprieta = schema.get("properties") or {}
    dall_argomento = None
    for chiave in ARGOMENTI_AGENTE:
        if chiave not in proprieta and chiave in argomenti:
            valore = argomenti.pop(chiave)
            dall_argomento = dall_argomento or valore
    for chiave in CHIAVI_AGENTE_META:
        valore = meta.get(chiave)
        if isinstance(valore, str) and valore.strip():
            return valore.strip()[:100]
    return dall_argomento.strip()[:100] if isinstance(dall_argomento, str) and dall_argomento.strip() else None


def _controlla(esposta, argomenti):
    """Gli errori dei parametri, per nome (mai il valore): mancanti, non previsti, di tipo sbagliato, vista non
    ammessa."""
    schema = esposta.schema()
    proprieta = schema.get("properties") or {}
    errori = [f"{_nome_parametro(k)}: parametro non previsto" for k in argomenti if k not in proprieta]
    errori += [f"{k}: obbligatorio" for k in schema.get("required", []) if argomenti.get(k) in (None, "")]
    for k, v in argomenti.items():
        tipo = (proprieta.get(k) or {}).get("type")
        attesi = TIPI_JSON.get(tipo) if isinstance(tipo, str) else None
        if attesi and v is not None and (not isinstance(v, attesi) or (tipo in ("integer", "number")
                                                                       and isinstance(v, bool))):
            errori.append(f"{k}: atteso {tipo}")
    if "vista" in proprieta and argomenti.get("vista") not in (None, ""):
        vista = argomenti["vista"]
        modulo = vista.split(".", 1)[0] if isinstance(vista, str) else ""
        if not isinstance(vista, str) or not esposta.ammette(vista) or modulo in operazioni.MODULI_ESCLUSI:
            errori.append("vista: non ammessa per questo strumento")
    return errori


def _registra(agente, esposta, argomenti, esito, motivo="", **altri):
    scrittura = esposta.effetto != "read"
    return Chiamata.objects.create(
        agente=agente, strumento=esposta.nome, vista=str(argomenti.get("vista") or "")[:80], effetto=esposta.effetto,
        esito=esito, motivo=motivo[:300], argomenti=_json(argomenti) if scrittura else {}, **altri)


def _json(valore):
    return json.loads(json.dumps(valore, ensure_ascii=False, default=str))


def chiama(nome, argomenti, meta):
    esposta = operazioni.per_nome(nome)
    if esposta is None:
        raise ErroreRpc(PARAMETRI_NON_VALIDI, "strumento sconosciuto o non ammesso")
    argomenti = dict(argomenti)
    nome_agente = _agente_indicato(argomenti, meta, esposta.schema())
    collegamento = Collegamento.attuale()
    azienda = collegamento.azienda
    if azienda is None or not azienda.attiva:
        return _risultato("Azienda degli agenti non configurata in AWF: nessuna operazione.",
                          {"stato": "non_configurato"}, errore=True)
    try:
        agente = agenti.risolvi(nome_agente, azienda)
    except agenti.AgenteSconosciuto:
        return _risultato("Agente sconosciuto o non attivo nell'ingaggio.", {"stato": "agente_sconosciuto"},
                          errore=True)
    agenti.confina(agente, azienda)
    type(agente).objects.filter(pk=agente.pk).update(ultimo_uso=timezone.now())
    errori = _controlla(esposta, argomenti)
    if errori:
        _registra(agente, esposta, argomenti, Chiamata.RIFIUTATA, "parametri non validi")
        return _risultato("Parametri non validi: " + "; ".join(errori) + ".",
                          {"stato": "parametri_non_validi", "errori": errori}, errore=True)

    from ai.strumenti import Contesto
    contesto = Contesto(utente=agente.utente, azienda=azienda)
    if esposta.effetto == "read":
        return _leggi(agente, esposta, contesto, argomenti)
    return _scrivi(agente, esposta, contesto, argomenti, meta, collegamento)


def _esegui(funzione, agente, esposta, argomenti):
    """(risultato, None) oppure (None, risposta di errore MCP)."""
    from ai.strumenti import ErroreStrumento
    try:
        return funzione(), None
    except ErroreStrumento as e:
        testo = _senza_valori(e, argomenti)
        stato = "errore"
    except PermissionDenied:
        testo, stato = "Permesso negato all'agente: l'operazione non è tra quelle concesse.", "permesso_negato"
    except (ObjectDoesNotExist, Http404):
        testo, stato = "Record non trovato o non visibile all'agente.", "non_trovato"
    except ValidationError as e:
        testo, stato = _senza_valori("; ".join(e.messages), argomenti), "non_valido"
    except TypeError:
        testo, stato = "Argomenti non validi per lo strumento.", "parametri_non_validi"
    except IntegrityError:
        raise                                           # chiave di idempotenza già usata: la gestisce _scrivi
    except Exception:
        log.exception("strumento %s per l'agente %s", esposta.nome, agente)
        testo, stato = "Errore interno: nessuna modifica salvata.", "errore"
    _registra(agente, esposta, argomenti, Chiamata.ERRORE, testo)
    return None, _risultato(testo, {"stato": stato, "dettaglio": testo}, errore=True)


def _uscita(risultato):
    """Il risultato di uno strumento come contenuto MCP: un oggetto JSON, con il record come vista e id."""
    if isinstance(risultato, dict):
        dati = dict(risultato)
    elif isinstance(risultato, list):
        dati = {"risultati": risultato}
    else:
        dati = {"risultato": "" if risultato is None else str(risultato)}
    record = dati.pop("record", None)
    if record is not None and getattr(record, "pk", None):
        dati["record"] = {"modello": record._meta.label_lower, "id": record.pk}
    return _json(dati)


def _leggi(agente, esposta, contesto, argomenti):
    risultato, errore = _esegui(lambda: esposta.strumento.funzione(contesto, **argomenti), agente, esposta, argomenti)
    if errore:
        return errore
    _registra(agente, esposta, argomenti, Chiamata.ESEGUITA)
    dati = _uscita(risultato)
    return _risultato(json.dumps(dati, ensure_ascii=False), dati)


def _anteprima(esposta, contesto, argomenti):
    a = esposta.strumento.anteprima(contesto, **argomenti) if esposta.strumento.anteprima else {}
    return a if isinstance(a, dict) else {}


def _scrivi(agente, esposta, contesto, argomenti, meta, collegamento):
    motivo = osservazione.motivo(collegamento)
    if motivo:
        return _osserva(agente, esposta, contesto, argomenti, motivo)
    chiave = meta.get("idempotencyKey")
    chiave = chiave[:200] if isinstance(chiave, str) else ""
    if chiave and (fatta := Chiamata.objects.filter(chiave_idempotenza=chiave, esito=Chiamata.ESEGUITA).first()):
        return _risultato(json.dumps(fatta.risultato, ensure_ascii=False), fatta.risultato)

    def esegui():
        with transaction.atomic():
            anteprima = _anteprima(esposta, contesto, argomenti)
            if anteprima.get("rischio") == "irreversibile" and esposta.effetto != "irreversible":
                raise PermissionDenied              # dichiarata ad Agate come scrittura: non si esegue
            risultato = esposta.strumento.funzione(contesto, **argomenti)
            if not isinstance(risultato, dict):
                risultato = {"esito": str(risultato or "Fatto.")}
            _nota_nel_chatter(risultato.get("record"), agente, anteprima)
            dati = _uscita(risultato)
            _registra(agente, esposta, argomenti, Chiamata.ESEGUITA, anteprima=_json(anteprima),
                      risultato=dati, chiave_idempotenza=chiave)
            return dati

    try:
        dati, errore = _esegui(esegui, agente, esposta, argomenti)
    except IntegrityError:                              # stessa chiave eseguita in parallelo: vale quella
        fatta = Chiamata.objects.filter(chiave_idempotenza=chiave, esito=Chiamata.ESEGUITA).first()
        if fatta is None:
            raise
        return _risultato(json.dumps(fatta.risultato, ensure_ascii=False), fatta.risultato)
    if errore:
        return errore
    return _risultato(json.dumps(dati, ensure_ascii=False), dati)


def _osserva(agente, esposta, contesto, argomenti, motivo):
    """Scrittura ferma: si registra con l'anteprima («cosa sarebbe successo»), che non tocca nulla."""
    from ai.strumenti import ErroreStrumento
    try:
        with transaction.atomic():
            anteprima = _json(_anteprima(esposta, contesto, argomenti))
    except (ErroreStrumento, PermissionDenied, ObjectDoesNotExist, Http404, ValidationError, TypeError) as e:
        anteprima = {"non_valida": _senza_valori(e, argomenti) or type(e).__name__}
    _registra(agente, esposta, argomenti, Chiamata.OSSERVAZIONE, motivo, anteprima=anteprima)
    sarebbe = {"strumento": esposta.nome, "effetto": esposta.effetto,
               "titolo": _senza_valori(anteprima.get("titolo", ""), argomenti)}
    return _risultato(f"Non eseguita: {motivo}. Le scritture degli agenti sono ferme; la richiesta è registrata "
                      "come «cosa sarebbe successo».",
                      {"stato": "osservazione", "codice": 409, "motivo": motivo, "sarebbe_successo": sarebbe},
                      errore=True)


def _nota_nel_chatter(obj, agente, anteprima):
    """Come le proposte dell'assistente: una voce di sistema nel chatter del record, se la vista lo ha."""
    from core import chatter
    from core.viste import registry
    vista = registry.per_modello(type(obj)) if obj is not None else None
    if vista is not None and vista.chatter and obj.pk:
        titolo = anteprima.get("titolo") or ""
        chatter.scrivi(obj, agente.utente, f"Tramite agente AWF {agente.nome}" + (f": {titolo}." if titolo else "."),
                       tipo="sistema")
