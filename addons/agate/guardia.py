"""La guardia di Agate sulle proposte dell'assistente AI.

Quando un utente conferma una modifica preparata dall'assistente, prima di eseguirla adabox chiede
ad Agate (`POST /v1/evaluate`, strumento `<prefisso>.<nome dello strumento>`):

- **consentita**: si esegue come sempre;
- **con un limite** (Agate ha cambiato i parametri, es. un importo oltre il tetto): non si esegue,
  si chiede all'assistente di rifarla entro il limite;
- **da approvare**: la proposta resta in attesa con il link alla console di Agate; quando una persona
  decide in Agate (webhook o controllo ogni minuto) si esegue o si chiude;
- **bloccata**: si chiude con il motivo di Agate;
- **Agate in osservazione** (l'environment di Agate, non questo modulo): non si esegue, con il verdetto.

In modalità *osservazione* di questo modulo Agate valuta e registra, ma adabox esegue comunque: serve
a vedere cosa cambierebbe prima di accendere. In modalità *attiva*, se Agate non risponde non si
esegue nulla.
"""
import logging

from django.utils import timezone

from . import cliente
from .models import Collegamento, Valutazione

log = logging.getLogger("agate.guardia")


def _link(collegamento, approval_id):
    if not collegamento.console_url:
        return ""
    return f"{collegamento.console_url.rstrip('/')}/console/approvals/{approval_id}/"


def _motivi(risposta):
    righe = [h.get("detail") or h.get("id") for h in risposta.get("policies_hit") or []
             if h.get("effect") != "allow"]
    fattori = risposta.get("risk", {}).get("factors") or []
    return "; ".join(dict.fromkeys(r for r in righe if r)) or ", ".join(fattori) or "regole dell'azienda"


def guardia(proposta, utente, azienda):
    from ai import proposte
    from ai.models import Proposta

    collegamento = Collegamento.attuale()
    if collegamento is None or collegamento.modalita == Collegamento.SPENTO:
        return None
    esistente = Valutazione.objects.filter(proposta=proposta).first()
    if esistente is not None and esistente.stato == Valutazione.IN_ATTESA:
        proposta.esito = "In attesa dell'approvazione in Agate."
        return proposta
    strumento = collegamento.strumento(proposta.strumento)
    attivo = collegamento.modalita == Collegamento.ATTIVO
    try:
        risposta = cliente.valuta(collegamento, strumento, proposta.argomenti, proposta.titolo,
                                  f"adabox:{utente.get_username()}")
    except cliente.ErroreAgate as e:
        log.warning("proposta %s: %s", proposta.pk, e)
        Valutazione.objects.update_or_create(proposta=proposta, defaults={
            "strumento": strumento, "stato": Valutazione.ERRORE, "motivo": str(e)[:500], "utente": utente})
        if not attivo:
            return None
        return proposte.chiudi(proposta, Proposta.FALLITA,
                               f"Agate non risponde ({e}): per sicurezza la modifica non è stata eseguita.")
    verdetto = str(risposta.get("verdict", ""))
    approvazione = risposta.get("approval") or {}
    valutazione, _ = Valutazione.objects.update_or_create(proposta=proposta, defaults={
        "strumento": strumento, "evaluation_id": risposta.get("evaluation_id", ""), "verdetto": verdetto,
        "approval_id": approvazione.get("id", ""), "utente": utente, "motivo": "",
        "stato": Valutazione.CONSENTITA})

    def segna(stato, motivo=""):
        valutazione.stato, valutazione.motivo = stato, motivo[:2000]
        valutazione.save(update_fields=["stato", "motivo"])

    if not attivo:                                       # osservazione di questo modulo: si registra e basta
        segna(Valutazione.OSSERVATA, f"Agate avrebbe detto: {verdetto}")
        return None
    if risposta.get("observed"):
        segna(Valutazione.OSSERVATA, f"Agate è in osservazione: avrebbe detto {verdetto}")
        return proposte.chiudi(proposta, Proposta.FALLITA,
                               f"Agate è in osservazione: non si esegue nulla (avrebbe detto «{verdetto}»).")
    if verdetto == "deny":
        motivo = _motivi(risposta)
        segna(Valutazione.NEGATA, motivo)
        return proposte.chiudi(proposta, Proposta.FALLITA, f"Fermata dalle regole di Agate: {motivo}.")
    if verdetto == "require_approval":
        if not valutazione.approval_id:
            segna(Valutazione.NEGATA, "approvazione richiesta ma non aperta")
            return proposte.chiudi(proposta, Proposta.FALLITA, "Agate chiede un'approvazione che non ha aperto.")
        segna(Valutazione.IN_ATTESA, _motivi(risposta))
        link = _link(collegamento, valutazione.approval_id)
        proposta.esito = ("Agate chiede l'approvazione di una persona: si esegue da sola quando arriva."
                          + (f" Decide chi approva qui: {link}" if link else ""))[:2000]
        proposta.save(update_fields=["esito"])
        return proposta
    if verdetto == "modify" and risposta.get("normalized_params") != proposta.argomenti:
        motivo = _motivi(risposta)
        segna(Valutazione.NEGATA, f"limite di Agate: {motivo}")
        return proposte.chiudi(proposta, Proposta.FALLITA,
                               f"Agate ammette la modifica solo entro un limite ({motivo}): chiedi all'assistente "
                               "di rifarla entro il limite.")
    return None


def _esito_negativo(stato, chi, motivo):
    """Il perché in parole, per chi aveva confermato la proposta."""
    if stato == "expired":
        return ("Nessuno ha deciso in tempo in Agate: la richiesta è scaduta e non è cambiato nulla. "
                "Se serve ancora, chiedila di nuovo all'assistente.")
    testo = "Non approvata in Agate" + (f" da {chi}" if chi else "")
    return testo + (f": «{motivo}»." if motivo else ".") + " Non è cambiato nulla."


def decisa(valutazione, stato, chi="", motivo=""):
    """Una persona ha deciso in Agate (`approved`, `rejected`) o la richiesta è scaduta (`expired`): si esegue la
    proposta, oppure si chiude con il motivo scritto da chi ha deciso."""
    from ai import proposte
    from ai.models import Proposta

    if valutazione.stato != Valutazione.IN_ATTESA:
        return valutazione
    proposta = valutazione.proposta
    valutazione.decisa = timezone.now()
    if stato != "approved":
        valutazione.stato = Valutazione.RIFIUTATA
        if motivo or stato == "expired":
            valutazione.motivo = (motivo or "scaduta senza decisione")[:300]
        valutazione.save(update_fields=["stato", "decisa", "motivo"])
        proposte.chiudi(proposta, Proposta.FALLITA, _esito_negativo(stato, chi, motivo))
        return valutazione
    valutazione.stato = Valutazione.APPROVATA
    valutazione.save(update_fields=["stato", "decisa"])
    from ai.strumenti import ErroreStrumento
    try:
        proposte.conferma(proposta, proposta.utente, proposta.azienda, guardie=False)
    except ErroreStrumento as e:
        proposte.chiudi(proposta, Proposta.FALLITA, str(e))
    return valutazione
