"""Scritture con conferma: l'assistente prepara una proposta (anteprima validata, nessuna modifica), l'utente la
conferma con un bottone e solo allora si esegue l'operazione salvata, con i permessi ricontrollati.

L'esito torna al modello nel <contesto> del messaggio successivo: il log degli eventi resta in sola aggiunta."""
import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Proposta
from .strumenti import Contesto, ErroreStrumento, disponibili

log = logging.getLogger("ai.proposte")

def prepara(strumento, contesto, argomenti):
    if contesto.conversazione is None:
        raise ErroreStrumento("Le modifiche si propongono solo in una chat con l'utente.")
    a = strumento.anteprima(contesto, **argomenti)
    p = Proposta.objects.create(
        conversazione=contesto.conversazione, turno=contesto.turno, utente=contesto.utente, azienda=contesto.azienda,
        strumento=strumento.nome, argomenti=argomenti, titolo=a["titolo"][:250], dettagli=a.get("dettagli", []),
        riepilogo=a.get("riepilogo", ""), rischio=a.get("rischio") or strumento.rischio,
        impronta=a.get("impronta", {}), url=a.get("url", ""))
    return (f"Proposta n. {p.pk} pronta: «{p.titolo}». NON è ancora eseguita: l'utente la vede sotto la tua risposta "
            "e la conferma con un bottone. Diglielo in una frase, senza ripetere i dettagli e senza dire che è fatta.")


def _chiudi(proposta, stato, esito, url=None):
    proposta.stato, proposta.esito, proposta.decisa = stato, esito[:2000], timezone.now()
    if url:
        proposta.url = url[:300]
    proposta.save(update_fields=["stato", "esito", "decisa", "url"])
    return proposta


def annulla(proposta):
    if proposta.stato == Proposta.IN_ATTESA:
        _chiudi(proposta, Proposta.ANNULLATA, "Annullata dall'utente.")
    return proposta


def conferma(proposta, utente, azienda):
    """Esegue la proposta se è ancora valida: in attesa, non scaduta, stessa azienda, strumento ancora permesso,
    record non cambiato dopo l'anteprima. Una sola esecuzione anche con due clic."""
    if proposta.stato != Proposta.IN_ATTESA:
        return proposta
    if proposta.scaduta:
        return _chiudi(proposta, Proposta.SCADUTA, "Scaduta: chiedi all'assistente di prepararla di nuovo.")
    if getattr(azienda, "pk", None) != proposta.azienda_id:
        raise ErroreStrumento(f"La proposta riguarda l'azienda «{proposta.azienda}»: passa a quell'azienda per "
                              "confermarla.")
    ambito = proposta.conversazione.ambito
    strumento = next((s for s in disponibili(utente, ambito) if s.nome == proposta.strumento), None)
    if not Proposta.objects.filter(pk=proposta.pk, stato=Proposta.IN_ATTESA).update(stato=Proposta.ESEGUITA,
                                                                                     decisa=timezone.now()):
        proposta.refresh_from_db()                                  # già decisa da un altro clic
        return proposta
    if strumento is None:
        return _chiudi(proposta, Proposta.FALLITA, "Operazione non più permessa per questo utente.")
    contesto = Contesto(utente=utente, azienda=azienda, conversazione=proposta.conversazione)
    try:
        with transaction.atomic():
            nuova = strumento.anteprima(contesto, **proposta.argomenti)          # di nuovo: permessi e validità
            if nuova.get("impronta", {}) != proposta.impronta:
                raise ErroreStrumento("Il record è cambiato dopo la proposta: chiedi all'assistente di rifarla.")
            risultato = strumento.funzione(contesto, **proposta.argomenti)
            if not isinstance(risultato, dict):
                risultato = {"esito": str(risultato or "Fatto.")}
            _nota_nel_chatter(risultato.get("record"), utente, proposta)
    except ErroreStrumento as e:
        return _chiudi(proposta, Proposta.FALLITA, str(e))
    except PermissionDenied:
        return _chiudi(proposta, Proposta.FALLITA, "Permesso negato.")
    except ValidationError as e:
        return _chiudi(proposta, Proposta.FALLITA, "; ".join(e.messages))
    except Exception:
        log.exception("proposta %s", proposta.pk)
        return _chiudi(proposta, Proposta.FALLITA, "Errore interno durante l'esecuzione: nessuna modifica salvata.")
    return _chiudi(proposta, Proposta.ESEGUITA, risultato.get("esito") or "Fatto.", risultato.get("url"))


def _nota_nel_chatter(obj, utente, proposta):
    from core import chatter
    from core.viste import registry
    vista = registry.per_modello(type(obj)) if obj is not None else None
    if vista is not None and vista.chatter and obj.pk:
        chatter.scrivi(obj, utente, f"Tramite l'assistente AI: {proposta.titolo}.", tipo="sistema")


def da_comunicare(conversazione):
    """Gli esiti delle proposte decise e non ancora passati al modello (e li segna come passati)."""
    proposte = list(conversazione.proposte.filter(comunicata=False).exclude(stato=Proposta.IN_ATTESA))
    Proposta.objects.filter(pk__in=[p.pk for p in proposte]).update(comunicata=True)
    return [f"Proposta n. {p.pk} «{p.titolo}»: {p.get_stato_display().lower()}"
            + (f" — {p.esito}" if p.esito else "") for p in proposte]
