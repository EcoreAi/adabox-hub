"""Controllo di quello che arriva dal costruttore delle regole: si salva solo ciò che il catalogo prevede."""
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from core import modelli_email
from core.models import ModelloEmail, TipoAttivita

from . import catalogo

MAX_VOCI = 10
OPERATORI = {"numero": {"maggiore", "minore", "uguale"}, "testo": {"contiene", "non_contiene", "uguale"},
             "sino": {"si", "no"}, "scelta": {"uguale", "diverso"}}


def utenti_di(azienda):
    return (get_user_model().objects.filter(is_active=True, profilo__aziende=azienda, profilo__esterno=False)
            .order_by("first_name", "username"))


def _lista(testo, nome):
    try:
        valore = json.loads(testo or "[]")
    except ValueError:
        raise ValidationError(f"{nome}: dati non validi.")
    if not isinstance(valore, list) or len(valore) > MAX_VOCI or not all(isinstance(v, dict) for v in valore):
        raise ValidationError(f"{nome}: al massimo {MAX_VOCI} voci.")
    return valore


def _condizione(c, dominio, errori):
    voce = dominio.condizioni.get(c.get("campo"))
    if voce is None:
        errori.append("Una condizione usa un dato che non esiste per questo tipo di record.")
        return None
    tipo, op, valore = voce[1], c.get("op"), str(c.get("valore", "")).strip()[:200]
    if op not in OPERATORI[tipo]:
        errori.append(f"Condizione «{voce[0]}»: confronto non valido.")
        return None
    if tipo == "numero":
        try:
            float(valore.replace(",", "."))
        except ValueError:
            errori.append(f"Condizione «{voce[0]}»: scrivi un numero.")
            return None
    elif tipo == "testo" and not valore:
        errori.append(f"Condizione «{voce[0]}»: scrivi il testo da cercare.")
        return None
    elif tipo == "scelta" and valore not in {str(k) for k, _ in voce[3]}:
        errori.append(f"Condizione «{voce[0]}»: scegli un valore.")
        return None
    return {"campo": c["campo"], "op": op, "valore": "" if tipo == "sino" else valore}


def _utente_valido(valore, azienda):
    return str(valore).isdigit() and utenti_di(azienda).filter(pk=int(valore)).exists()


def _testo_campi(testo, dominio):
    return modelli_email.segnaposto_in(testo) - set(dominio.campi) - set(modelli_email.CAMPI_SEMPRE)


def _azione(a, dominio, azienda, errori):
    tipo = a.get("tipo")
    if tipo == "email":
        if not ModelloEmail.objects.filter(azienda=azienda, codice=a.get("modello"), dominio=dominio.codice).exists():
            errori.append("Scegli il modello dell'email da mandare.")
            return None
        dest = a.get("a")
        pulita = {"tipo": tipo, "modello": a["modello"], "a": dest}
        if dest == "indirizzo":
            try:
                validate_email(a.get("indirizzo", ""))
            except ValidationError:
                errori.append("Scrivi un indirizzo email valido per il destinatario.")
                return None
            pulita["indirizzo"] = a["indirizzo"]
        elif dest == "utente":
            if not _utente_valido(a.get("utente"), azienda):
                errori.append("Scegli la persona a cui mandare l'email.")
                return None
            pulita["utente"] = int(a["utente"])
        elif dest not in dominio.esterni and dest not in dominio.interni:
            errori.append("Scegli a chi mandare l'email.")
            return None
        return pulita
    if tipo == "attivita":
        dest, testo = a.get("a"), str(a.get("testo", "")).strip()[:200]
        pulita = {"tipo": tipo, "a": dest, "testo": testo}
        if not testo:
            errori.append("Scrivi che cosa deve fare chi riceve l'attività.")
            return None
        if dest == "utente":
            if not _utente_valido(a.get("utente"), azienda):
                errori.append("Scegli la persona a cui dare l'attività.")
                return None
            pulita["utente"] = int(a["utente"])
        elif dest not in dominio.interni:
            errori.append("Scegli a chi dare l'attività.")
            return None
        if not TipoAttivita.objects.filter(pk=a.get("tipo_attivita") or 0).exists():
            errori.append("Scegli il tipo di attività.")
            return None
        giorni = str(a.get("giorni", "0"))
        pulita.update(tipo_attivita=int(a["tipo_attivita"]), giorni=min(int(giorni), 365) if giorni.isdigit() else 0)
    elif tipo == "nota":
        testo = str(a.get("testo", "")).strip()[:2000]
        if not testo:
            errori.append("Scrivi il testo della nota.")
            return None
        pulita = {"tipo": tipo, "testo": testo}
    elif tipo == "assegna":
        if not dominio.assegna or not _utente_valido(a.get("utente"), azienda):
            errori.append("Scegli la persona a cui assegnare il record.")
            return None
        return {"tipo": tipo, "utente": int(a["utente"])}
    else:
        errori.append("Azione sconosciuta.")
        return None
    if sconosciuti := _testo_campi(pulita["testo"], dominio):
        errori.append(f"Il campo {{{{ {sorted(sconosciuti)[0]} }}}} non esiste per questo tipo di record.")
        return None
    return pulita


def pulisci(dati, azienda):
    """I valori puliti della regola, oppure ValidationError con tutti i problemi in parole."""
    errori = []
    nome = (dati.get("nome") or "").strip()[:120]
    if not nome:
        errori.append("Dai un nome alla regola.")
    evento = catalogo.evento(dati.get("evento"))
    if evento is None:
        raise ValidationError(errori + ["Scegli quando deve scattare la regola."])
    dominio = catalogo.domini()[evento.dominio]
    giorni = 0
    if evento.giorni:
        testo = str(dati.get("giorni", "")).strip()
        if not testo.isdigit() or int(testo) > 3650:
            errori.append("Scrivi il numero di giorni.")
        else:
            giorni = int(testo)
    grezze = [_lista(dati.get("condizioni"), "Condizioni"), _lista(dati.get("azioni"), "Azioni")]
    condizioni = [c for c in (_condizione(c, dominio, errori) for c in grezze[0]) if c]
    azioni = [a for a in (_azione(a, dominio, azienda, errori) for a in grezze[1]) if a]
    if not azioni and not grezze[1]:
        errori.append("Aggiungi almeno un'azione: che cosa deve succedere?")
    if errori:
        raise ValidationError(errori)
    return {"nome": nome, "evento": evento.codice, "giorni": giorni, "condizioni": condizioni, "azioni": azioni}


def descrivi_quando(regola):
    evento = catalogo.evento(regola.evento)
    if evento is None:
        return "Evento non più disponibile"
    return f"{evento.nome} {evento.giorni.format(n=regola.giorni)}".strip()


def descrivi_condizioni(regola):
    dominio = catalogo.dominio_di(regola.evento)
    if dominio is None:
        return []
    parole = {"maggiore": "è almeno", "minore": "è al massimo", "uguale": "è", "contiene": "contiene",
              "non_contiene": "non contiene", "diverso": "non è"}
    voci = []
    for c in regola.condizioni:
        voce = dominio.condizioni.get(c.get("campo"))
        if voce is None:
            continue
        if voce[1] == "sino":
            voci.append(voce[0] if c["op"] == "si" else f"Non: {voce[0].lower()}")
        else:
            valore = dict(voce[3]).get(c["valore"], c["valore"]) if voce[1] == "scelta" else c["valore"]
            voci.append(f"{voce[0]} {parole.get(c['op'], c['op'])} {valore}")
    return voci


def descrivi_azioni(regola):
    dominio = catalogo.dominio_di(regola.evento)
    if dominio is None:
        return []
    modelli = dict(ModelloEmail.objects.filter(azienda=regola.azienda).values_list("codice", "nome"))
    persone = {u.pk: catalogo._nome(u) for u in utenti_di(regola.azienda)}

    def chi(a):
        ruolo = a.get("a")
        if ruolo == "utente":
            return persone.get(a.get("utente"), "una persona non più attiva")
        if ruolo == "indirizzo":
            return a.get("indirizzo", "")
        voce = dominio.esterni.get(ruolo) or dominio.interni.get(ruolo)
        return voce[0].lower() if voce else "—"

    voci = []
    for a in regola.azioni:
        if a["tipo"] == "email":
            voci.append({"icona": "inbox", "testo": f"Manda «{modelli.get(a['modello'], 'modello eliminato')}» a {chi(a)}"})
        elif a["tipo"] == "attivita":
            voci.append({"icona": "check", "testo": f"Dai a {chi(a)} l'attività «{a['testo']}»"})
        elif a["tipo"] == "nota":
            voci.append({"icona": "edit", "testo": f"Scrivi la nota «{a['testo'][:80]}»"})
        elif a["tipo"] == "assegna":
            voci.append({"icona": "user", "testo": f"Assegna a {persone.get(a.get('utente'), 'una persona non più attiva')}"})
    return voci


def modelli_usati_da(azienda, codice):
    from .models import Regola
    return [r for r in Regola.objects.filter(azienda=azienda) if any(a.get("modello") == codice for a in r.azioni)]
