"""Il motore delle regole. Gli eventi al salvataggio accodano un lavoro; quelli a tempo li controlla un lavoro ogni ora.

Tre garanzie: una regola non ne fa scattare altre (niente catene infinite), un evento a tempo agisce una volta sola per
record (Esecuzione.chiave), e un giro non manda più di MAX_PER_GIRO esecuzioni per regola: le altre aspettano il prossimo."""
import logging
from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import attivita, chatter, lavori, modelli_email
from core.generici import ct_di
from core.models import Messaggio, ModelloEmail, TipoAttivita
from core.registry.modules import disattivati

from . import catalogo
from .models import Esecuzione, Regola

log = logging.getLogger("automazioni")
MAX_PER_GIRO = 100
ORA_INIZIO = 8                      # le regole a tempo non urgenti partono dalle 8: nessun sollecito di notte
_in_azione = ContextVar("automazioni_in_azione", default=False)


class Saltata(Exception):
    """L'azione non si può fare su questo record (manca l'email, manca la persona): non è un guasto."""


# ---------- eventi al salvataggio

def _regole_attive(azienda_id, codici):
    return Regola.objects.filter(azienda_id=azienda_id, attiva=True, evento__in=codici)


def prima_di_salvare(sender, instance, raw=False, **kwargs):
    if raw or _in_azione.get() or not instance.pk or not hasattr(instance, "azienda_id"):
        return
    eventi = catalogo.eventi_del_modello(sender)
    campi = sorted({c for e in eventi for c in e.osserva})
    if campi and _regole_attive(instance.azienda_id, [e.codice for e in eventi]).exists():
        instance._automazioni_prima = sender._base_manager.filter(pk=instance.pk).values(*campi).first() or {}


def dopo_il_salvataggio(sender, instance, created, raw=False, **kwargs):
    """Non deve mai impedire il salvataggio del record: un errore qui finisce nel log."""
    if raw or _in_azione.get() or not hasattr(instance, "azienda_id"):
        return
    try:
        eventi = {e.codice: e for e in catalogo.eventi_del_modello(sender)}
        regole = list(_regole_attive(instance.azienda_id, list(eventi))) if eventi else []
        if not regole or "automazioni" in disattivati():
            return
        prima = getattr(instance, "_automazioni_prima", {})
        for regola in regole:
            if eventi[regola.evento].scatta(prima, instance, created):
                lavori.accoda("automazioni.motore.esegui_evento", max_tentativi=1, azienda=instance.azienda,
                              regola_id=regola.pk, ct_id=ct_di(instance).pk, object_id=instance.pk)
    except Exception:
        log.exception("automazioni: valutazione di %s %s", sender.__name__, instance.pk)


def esegui_evento(regola_id, ct_id, object_id):
    regola = Regola.objects.filter(pk=regola_id, attiva=True).first()
    record = ContentType.objects.get_for_id(ct_id).model_class()._base_manager.filter(pk=object_id).first() if regola else None
    if regola is None or record is None:
        return "regola spenta"
    esecuzione = applica(regola, record)
    return esecuzione.get_esito_display() if esecuzione else "condizioni non vere"


# ---------- condizioni

def _numero(valore):
    try:
        return Decimal(str(valore).replace(",", "."))
    except InvalidOperation:
        return None


def vera(condizione, dominio, record):
    voce = dominio.condizioni.get(condizione.get("campo"))
    if voce is None:
        return False
    tipo, valore = voce[1], voce[2](record)
    op, atteso = condizione.get("op"), condizione.get("valore", "")
    if tipo == "sino":
        return bool(valore) == (op != "no")
    if tipo == "numero":
        a, b = _numero(valore), _numero(atteso)
        if a is None or b is None:
            return False
        return {"maggiore": a >= b, "minore": a <= b, "uguale": a == b}.get(op, False)
    if tipo == "scelta":
        return (str(valore) == str(atteso)) == (op != "diverso")
    testo, cercato = str(valore or "").lower(), str(atteso).lower()
    return {"contiene": cercato in testo, "non_contiene": cercato not in testo, "uguale": testo == cercato}.get(op, False)


def tutte_vere(regola, dominio, record):
    return all(vera(c, dominio, record) for c in regola.condizioni)


# ---------- azioni

def _persona(azione, dominio, record):
    if azione.get("a") == "utente":
        return get_user_model().objects.filter(pk=azione.get("utente"), is_active=True).first()
    voce = dominio.interni.get(azione.get("a"))
    return voce[1](record) if voce else None


def _indirizzo(azione, dominio, record):
    a = azione.get("a")
    if a == "indirizzo":
        return azione.get("indirizzo", "")
    if a in dominio.esterni:
        return dominio.esterni[a][1](record) or ""
    persona = _persona(azione, dominio, record)
    return persona.email if persona else ""


def _email(azione, regola, dominio, record, valori, simula):
    modello = ModelloEmail.objects.filter(azienda=regola.azienda, codice=azione.get("modello"), dominio=dominio.codice).first()
    if modello is None:
        raise Saltata("il modello dell'email non esiste più")
    indirizzo = _indirizzo(azione, dominio, record)
    if not indirizzo:
        raise Saltata("il destinatario non ha un indirizzo email")
    email = modelli_email.messaggio_da(modello.oggetto, modello.corpo, valori, regola.azienda, [indirizzo])
    if simula:
        return {"testo": f"Email a {indirizzo}: «{email.subject}»", "corpo": email.body}
    email.send()
    chatter.scrivi(record, None, f"Email «{email.subject}» inviata a {indirizzo} dalla regola «{regola}».", tipo=Messaggio.SISTEMA)
    return f"Email a {indirizzo}: «{email.subject}»"


def _attivita(azione, regola, dominio, record, valori, simula):
    persona = _persona(azione, dominio, record)
    if persona is None:
        raise Saltata("non c'è una persona a cui dare l'attività")
    tipo = TipoAttivita.objects.filter(pk=azione.get("tipo_attivita")).first() or TipoAttivita.objects.first()
    if tipo is None:
        raise Saltata("non esistono tipi di attività")
    riepilogo = modelli_email.riempi(azione.get("testo", ""), valori)[:200]
    testo = f"Attività per {catalogo._nome(persona)}: «{riepilogo}»"
    if not simula:
        scadenza = timezone.localdate() + timedelta(days=int(azione.get("giorni") or 0))
        attivita.pianifica(record, tipo, persona, scadenza=scadenza, riepilogo=riepilogo)
    return testo


def _nota(azione, regola, dominio, record, valori, simula):
    testo = modelli_email.riempi(azione.get("testo", ""), valori)
    if not simula:
        chatter.scrivi(record, None, testo, tipo=Messaggio.SISTEMA)
    return f"Nota: «{testo[:120]}»"


def _assegna(azione, regola, dominio, record, valori, simula):
    persona = get_user_model().objects.filter(pk=azione.get("utente"), is_active=True).first()
    if not dominio.assegna or persona is None:
        raise Saltata("la persona non c'è più")
    if getattr(record, f"{dominio.assegna}_id") == persona.pk:
        return f"Già assegnato a {catalogo._nome(persona)}"
    if not simula:
        vecchi = chatter.valori(record, [dominio.assegna])
        setattr(record, dominio.assegna, persona)
        record.save(update_fields=[dominio.assegna])
        chatter.traccia(record, vecchi, None)
    return f"Assegnato a {catalogo._nome(persona)}"


AZIONI = {"email": _email, "attivita": _attivita, "nota": _nota, "assegna": _assegna}


def _fai(regola, record, extra, simula):
    """[(testo, esito)] di tutte le azioni: se una non riesce, le altre si fanno lo stesso."""
    dominio = catalogo.dominio_di(regola.evento)
    valori = {**dominio.valori(record), **extra}
    risultato = []
    gettone = _in_azione.set(True)
    try:
        for azione in regola.azioni:
            try:
                with transaction.atomic():
                    fatto = AZIONI[azione["tipo"]](azione, regola, dominio, record, valori, simula)
                risultato.append({"esito": Esecuzione.FATTA, **(fatto if isinstance(fatto, dict) else {"testo": fatto})})
            except Saltata as e:
                risultato.append({"esito": Esecuzione.SALTATA, "testo": str(e).capitalize()})
            except Exception as e:
                log.exception("automazioni: regola %s su %s", regola.pk, record)
                risultato.append({"esito": Esecuzione.ERRORE, "testo": f"Errore: {e}"[:300]})
    finally:
        _in_azione.reset(gettone)
    return risultato


def _esito(passi):
    esiti = {p["esito"] for p in passi}
    return Esecuzione.ERRORE if Esecuzione.ERRORE in esiti else Esecuzione.SALTATA if Esecuzione.SALTATA in esiti else Esecuzione.FATTA


def applica(regola, record, chiave=None, extra=None):
    """Controlla le condizioni e fa le azioni; None se le condizioni non valgono o se con questa chiave è già stata fatta."""
    dominio = catalogo.dominio_di(regola.evento)
    if dominio is None or not tutte_vere(regola, dominio, record):
        return None
    extra = {k: str(v) for k, v in (extra or {}).items()}
    try:
        with transaction.atomic():              # prima la riga: due lavori insieme non mandano due solleciti
            esecuzione = Esecuzione.objects.create(regola=regola, content_type=ct_di(record), object_id=record.pk,
                                                   nome_record=str(record)[:200], chiave=chiave, extra=extra)
    except IntegrityError:
        return None
    passi = _fai(regola, record, extra, simula=False)
    esecuzione.dettaglio, esecuzione.esito = passi, _esito(passi)
    esecuzione.save(update_fields=["dettaglio", "esito"])
    return esecuzione


def simula(regola, record, extra=None):
    """Che cosa farebbe sul record, senza mandare né scrivere nulla."""
    return _fai(regola, record, {k: str(v) for k, v in (extra or {}).items()}, simula=True)


# ---------- eventi a tempo

def _gia_fatte(regola):
    return {(c, o, k) for c, o, k in regola.esecuzioni.exclude(chiave=None).values_list("content_type_id", "object_id", "chiave")}


def in_attesa(regola):
    """[(record, chiave, extra)] su cui la regola a tempo agirebbe adesso."""
    evento, dominio = catalogo.evento(regola.evento), catalogo.dominio_di(regola.evento)
    if evento is None or not evento.a_tempo:
        return []
    fatte = _gia_fatte(regola)
    return [(r, k, e) for r, k, e in evento.cerca(regola.azienda, regola.giorni)
            if (ct_di(r).pk, r.pk, k) not in fatte and tutte_vere(regola, dominio, r)]


def controlla_tempo():
    """Ogni ora. Una regola che fallisce non ferma le altre."""
    adesso = timezone.localtime()
    fatte = 0
    for regola in Regola.objects.filter(attiva=True).select_related("azienda"):
        evento = catalogo.evento(regola.evento)
        if evento is None or not evento.a_tempo or (adesso.hour < ORA_INIZIO and not evento.urgente):
            continue
        try:
            with transaction.atomic():
                for record, chiave, extra in in_attesa(regola)[:MAX_PER_GIRO]:
                    if applica(regola, record, chiave, extra):
                        fatte += 1
        except Exception:
            log.exception("automazioni: regola a tempo %s", regola.pk)
    return f"{fatte} esecuzioni"


def accendi(regola, anche_esistenti=False):
    """Accende la regola. Se non deve toccare ciò che è già in attesa, lo segna come saltato: partirà solo da ora in poi."""
    if not anche_esistenti:
        for record, chiave, extra in in_attesa(regola):
            Esecuzione.objects.get_or_create(
                regola=regola, content_type=ct_di(record), object_id=record.pk, chiave=chiave,
                defaults={"nome_record": str(record)[:200], "esito": Esecuzione.SALTATA, "extra": {k: str(v) for k, v in extra.items()},
                          "dettaglio": [{"esito": Esecuzione.SALTATA, "testo": "Era già in attesa quando la regola è stata accesa"}]})
    regola.attiva, regola.attivata_il = True, timezone.now()
    regola.save(update_fields=["attiva", "attivata_il"])


def riprova(esecuzione):
    """Rifà le azioni di un'esecuzione non riuscita o saltata."""
    regola, record, chiave, extra = esecuzione.regola, esecuzione.record, esecuzione.chiave, esecuzione.extra
    if record is None:
        return None
    esecuzione.delete()
    return applica(regola, record, chiave, extra)
