"""Le azioni degli agenti in attesa dette in parole, per «Da approvare»: «Il Qualificatore lead chiede di cambiare
«Preventivo gestionale per 3 negozi»: fase → Qualificata», mai «awf.modifica_record».

Il webhook di Agate (`approval.requested`) porta lo strumento e un riepilogo già mascherato («awf.modifica_record.
Motivi: …; <motivazione dell'agente>»). Se porta anche i parametri (`params`) e chi chiede (`actor`), la frase li usa:
il record si legge in adabox (vista e id), i campi con le loro etichette. Quello che manca si ricava dal riepilogo
(il primo «…» è la cosa di cui si parla) o si dice in generale; chi chiede, se non è indicato, è l'unico agente del
contratto, altrimenti «Un agente»."""
import datetime
import logging
import re

from .models import Agente

log = logging.getLogger("awf.frasi")

VERBI = {"modifica_record": "cambiare", "crea_record": "creare", "elimina_record": "eliminare",
         "pianifica_attivita": "lasciare un'attività su", "esegui_bottone": "premere «{}» su",
         "esegui_azione": "fare «{}» su"}
SENZA_NOME = {"esegui_bottone": "premere un bottone su", "esegui_azione": "fare un'azione su"}
METODO = {"esegui_bottone": "bottone", "esegui_azione": "azione"}
CITATO_RE = re.compile(r"«([^«»]{1,200})»")
DATA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_CAMPI = 5


def _articolo(nome):
    """«Il Qualificatore lead», «L'Assistente vendite», «Lo Smistatore»: l'articolo per un ruolo detto al maschile."""
    minuscolo = nome.lower()
    if minuscolo[:1] in "aeiouhàèéìòù":
        return f"L'{nome}"
    if re.match(r"^(s[^aeiou]|z|gn|ps|x|y|pn)", minuscolo):
        return f"Lo {nome}"
    return f"Il {nome}"


def chi(a):
    """Chi chiede: l'agente indicato dal webhook, l'unico agente del contratto, o «Un agente»."""
    agenti = Agente.objects.filter(attivo=True, tecnico=False)
    if a.attore:
        agente = (agenti.filter(agate_agent_id=a.attore).first() or agenti.filter(nome__iexact=a.attore).first())
        if agente is not None:
            return _articolo(agente.nome)
    unici = list(agenti[:2])
    return _articolo(unici[0].nome) if len(unici) == 1 else "Un agente"


def _vista(nome):
    from . import operazioni
    try:
        return operazioni.viste().get(nome) if isinstance(nome, str) else None
    except Exception:                                   # registro delle viste non leggibile: si dice in generale
        log.warning("viste non leggibili", exc_info=True)
        return None


def _record(v, pk):
    if v is None or isinstance(pk, bool) or not isinstance(pk, (int, str)) or not str(pk).isdigit():
        return None
    try:
        return v.model._default_manager.filter(pk=int(pk)).first()
    except Exception:
        return None


def _nome(obj):
    try:
        testo = str(obj)
    except Exception:
        return ""
    return "" if testo in ("", "None") or testo.endswith(" object (None)") else testo[:200]


def _valore(campo, valore):
    """Il valore come lo vede una persona: l'etichetta di una scelta, il nome del record collegato, sì/no, la data."""
    if valore in (None, "", []):
        return "—"
    if isinstance(valore, bool):
        return "sì" if valore else "no"
    if campo is not None:
        if getattr(campo, "choices", None):
            scelte = dict(campo.flatchoices)
            return str(scelte.get(valore, scelte.get(str(valore), valore)))
        if campo.is_relation and getattr(campo, "related_model", None) is not None:
            ids = valore if isinstance(valore, list) else [valore]
            nomi = [_nome(o) for o in campo.related_model._default_manager.filter(
                pk__in=[i for i in ids if str(i).isdigit()])]
            if nomi:
                return ", ".join(n for n in nomi if n) or "—"
    if isinstance(valore, str) and DATA_RE.match(valore):
        try:
            return datetime.date.fromisoformat(valore).strftime("%d/%m/%Y")
        except ValueError:
            return valore
    if isinstance(valore, (list, tuple)):
        return ", ".join(str(x) for x in valore)
    return str(valore)[:200]


def _campi(v, campi):
    """«fase → Qualificata, probabilità → 60»: i campi indicati con l'etichetta del modello."""
    if not isinstance(campi, dict):
        return ""
    righe = []
    for nome, valore in campi.items():
        if nome == "campi_personalizzati" and isinstance(valore, dict):
            righe += [f"{k} → {_valore(None, x)}" for k, x in valore.items()]
            continue
        campo = None
        if v is not None:
            try:
                campo = v.model._meta.get_field(nome)
            except Exception:
                campo = None
        etichetta = str(campo.verbose_name) if campo is not None and getattr(campo, "verbose_name", None) else \
            str(nome).replace("_", " ")
        righe.append(f"{etichetta} → {_valore(campo, valore)}")
    testo = ", ".join(righe[:MAX_CAMPI])
    return testo + (f" e altri {len(righe) - MAX_CAMPI}" if len(righe) > MAX_CAMPI else "")


def _etichetta_metodo(v, nome):
    if v is not None and isinstance(nome, str) and hasattr(v, nome):
        return str(v.etichetta_metodo(nome))
    return str(nome or "").replace("_", " ")


def _riepilogo(a, strumento):
    """Il riepilogo di Agate senza il nome tecnico dello strumento in testa («awf.modifica_record. Motivi: …»)."""
    testo = (a.riepilogo or "").strip()
    if a.strumento and testo.startswith(a.strumento):
        testo = testo[len(a.strumento):].lstrip(" .,;:")
    elif strumento and testo.startswith(strumento):
        testo = testo[len(strumento):].lstrip(" .,;:")
    if testo in (f"Azione {a.strumento} in attesa di approvazione", "Azione in attesa di approvazione"):
        return ""                                        # il riepilogo di ripiego del webhook: non dice di più
    return testo[:1].upper() + testo[1:] if testo else ""


def _dal_parametri(strumento, p):
    """(cosa, dettagli) dai parametri dell'azione, o ("", "")."""
    v = _vista(p.get("vista"))
    dove = str(v.verbose_name_plural or v.verbose_name) if v is not None else ""
    if strumento == "crea_record":
        cosa = f"una voce in «{dove[:1].upper() + dove[1:]}»" if dove else "una voce nuova"
        return cosa, _campi(v, p.get("campi"))
    if strumento == "esegui_azione":
        ids = p.get("ids") if isinstance(p.get("ids"), list) else []
        cosa = f"{len(ids)} record" + (f" di «{dove}»" if dove else "") if ids else ""
        return cosa, ""
    obj = _record(v, p.get("id"))
    nome = _nome(obj) if obj is not None else ""
    cosa = f"«{nome}»" if nome else ""
    if strumento == "modifica_record":
        return cosa, _campi(v, p.get("campi"))
    if strumento == "pianifica_attivita":
        dettagli = [str(p.get("tipo") or "").strip()]
        if isinstance(p.get("scadenza"), str) and p["scadenza"]:
            dettagli.append(f"entro il {_valore(None, p['scadenza'])}")
        if isinstance(p.get("riepilogo"), str) and p["riepilogo"].strip():
            dettagli.append(f"«{p['riepilogo'].strip()[:200]}»")
        return cosa, ", ".join(x for x in dettagli if x)
    return cosa, ""


def approvazione(a):
    """{frase, dettaglio} di un'azione di un agente in attesa (`Approvazione`, non del contratto)."""
    strumento = (a.strumento or "").rsplit(".", 1)[-1]
    parametri = a.parametri if isinstance(a.parametri, dict) else {}
    riepilogo = _riepilogo(a, strumento)
    cosa, dettagli = "", ""
    if parametri:
        try:
            cosa, dettagli = _dal_parametri(strumento, parametri)
        except Exception:                               # parametri strani: si dice in generale
            log.warning("approvazione %s: parametri non leggibili", a.approval_id, exc_info=True)
    if not cosa and (citato := CITATO_RE.search(riepilogo)):
        cosa = f"«{citato.group(1).strip()}»"
    verbo = VERBI.get(strumento)
    if verbo is None:
        frase = f"{chi(a)} chiede il tuo ok per un'azione" + (f" su {cosa}" if cosa else "")
    else:
        if strumento in METODO:
            etichetta = _etichetta_metodo(_vista(parametri.get("vista")), parametri.get(METODO[strumento]))
            verbo = verbo.format(etichetta) if etichetta else SENZA_NOME[strumento]
        if not cosa:
            cosa = {"crea_record": "una voce nuova", "esegui_azione": "alcuni record"}.get(strumento, "un record")
        frase = f"{chi(a)} chiede di {verbo} {cosa}"
    if dettagli:
        frase += f": {dettagli}"
    return {"frase": frase, "dettaglio": riepilogo}
