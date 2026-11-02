"""«Da approvare»: in una pagina sola quello che aspetta una persona, deciso in adabox a nome di chi clicca (§8.4).

- **Le azioni degli agenti** (modulo `awf`, dal webhook `approval.requested`), per chi gestisce gli agenti, in una
  frase semplice («Il Qualificatore lead chiede di cambiare «Preventivo…»: fase → Qualificata», `awf.frasi`);
- **le proposte dell'assistente** in attesa dell'ok (le valutazioni `in_attesa`), per chi gestisce il Controllo AI;
- **i contratti degli agenti** da confermare di nuovo (proposti diversi da quello confermato): qui c'è il link alla
  pagina della richiesta, che mostra cosa è cambiato.

Approva e Rifiuta (con un motivo facoltativo) vanno ad Agate con la chiave `decide` e il nome della persona
(`decided_by`); lo stato locale si aggiorna subito, il webhook `approval.decided` lo conferma dopo. Per approvare
un'azione irreversibile (o che riguarda il contratto) la persona riscrive la password; rifiutare non la chiede mai: non
cambia nulla. Senza il collegamento con un codice resta il link «Decidi in Agate»."""
import logging

from django.conf import settings
from django.utils import timezone

from core.registry.modules import disattivati

from . import applicazione, cliente
from .guardia import decisa
from .models import Valutazione

log = logging.getLogger("agate.decisioni")

AGENTE, ASSISTENTE, CONTRATTO = "agente", "assistente", "contratto"
PERMESSO_AGATE, PERMESSO_AWF = "agate.change_collegamento", "awf.change_collegamento"


def _awf():
    return "awf" in settings.ADDONS_ATTIVI and "awf" not in disattivati()


def vede_agenti(utente):
    return _awf() and utente.has_perm(PERMESSO_AWF)


def vede_assistente(utente):
    return utente.has_perm(PERMESSO_AGATE)


def puo_vedere(utente):
    return utente.is_authenticated and (vede_agenti(utente) or vede_assistente(utente))


def _approvazioni():
    from awf.models import Approvazione
    from django.db.models import Q
    return (Approvazione.objects.filter(stato=Approvazione.IN_ATTESA)
            .filter(Q(scade__isnull=True) | Q(scade__gt=timezone.now())))


def _valutazioni():
    return Valutazione.objects.filter(stato=Valutazione.IN_ATTESA).exclude(approval_id="")


def conteggio(utente):
    """Quante cose aspettano questa persona: il numero accanto a «Da approvare» nel menu del profilo."""
    if not utente.is_authenticated:
        return 0
    n = 0
    if vede_agenti(utente):
        from awf import contratto
        n += _approvazioni().count() + contratto.da_confermare().count()
    if vede_assistente(utente):
        n += _valutazioni().count()
    return n


# ---------- le voci, in parole ----------

def irreversibile_agente(a):
    """Un'azione degli agenti si approva con la password se è irreversibile, se lo strumento non è (più) fra quelli
    esposti (per prudenza) o se riguarda il contratto."""
    if a.contratto:
        return True
    from awf import operazioni
    nome = a.strumento.split(".", 1)[1] if a.strumento.startswith("awf.") else a.strumento
    esposta = operazioni.per_nome(nome)
    return esposta is None or esposta.effetto == "irreversible"


def irreversibile_assistente(v):
    from ai.strumenti import app
    from ai.strumenti.registro import _registro
    app.carica()
    strumento = _registro.get(v.proposta.strumento)
    return strumento is None or strumento.rischio == "irreversibile"


def _persona(u):
    return (u.get_full_name() or u.get_username()) if u is not None else "Qualcuno"


def voci(utente, console=""):
    """[{tipo, pk, frase, dettaglio, quando, scade, password, link, link_agate, in_conferma}] per questa persona."""
    righe = []
    if vede_agenti(utente):
        from awf import contratto
        from awf.templatetags.awf import nome_squadra
        for r in contratto.da_confermare():
            righe.append({"tipo": CONTRATTO, "pk": r.pk, "quando": r.aggiornata, "scade": None, "password": True,
                          "frase": f"Il contratto per «{nome_squadra(r.team_nome) or r.team_slug}» è diverso da quello "
                                   "che è stato confermato: va rivisto.",
                          "dettaglio": "; ".join(contratto.differenze(r.consenso, r.proposta)),
                          "link": _url("awf:richiesta", r.pk), "link_agate": r.approve_url, "in_conferma": False})
        from awf import frasi
        for a in _approvazioni():
            testo = ({"frase": f"Contratto degli agenti: «{a.riepilogo}»", "dettaglio": ""} if a.contratto
                     else frasi.approvazione(a))
            righe.append({"tipo": AGENTE, "pk": a.pk, "quando": a.ricevuta, "scade": a.scade,
                          "password": irreversibile_agente(a), "frase": testo["frase"],
                          "dettaglio": testo["dettaglio"], "link": "",
                          "link_agate": f"{console}/console/approvals/{a.approval_id}/" if console else "",
                          "in_conferma": a.in_conferma})
    if vede_assistente(utente):
        for v in _valutazioni().select_related("proposta", "utente"):
            righe.append({"tipo": ASSISTENTE, "pk": v.pk, "quando": v.creata, "scade": None,
                          "password": irreversibile_assistente(v),
                          "frase": f"{_persona(v.utente)} ha chiesto all'assistente: «{v.proposta.titolo}»",
                          "dettaglio": v.motivo, "link": "",
                          "link_agate": f"{console}/console/approvals/{v.approval_id}/" if console else "",
                          "in_conferma": False})
    return sorted(righe, key=lambda x: x["quando"], reverse=True)


def _url(nome, pk):
    from django.urls import reverse
    return reverse(nome, args=[pk])


# ---------- decidere ----------

class Rifiutata(Exception):
    """La decisione non è partita: il messaggio è per la persona."""


def _ad_agate(approval_id, approva, utente, motivo):
    if not applicazione.semplice():
        raise Rifiutata("Qui si decide solo con il Controllo AI collegato con un codice: usa «Decidi in Agate».")
    testo = motivo or applicazione.motivo(azione="Approvato" if approva else "Rifiutato")
    try:
        return applicazione.decidi(approval_id, "approved" if approva else "rejected", utente, testo)
    except cliente.ErroreAgate as e:
        if e.stato == 409:
            return None                                 # già decisa: da un'altra persona o nella console
        log.warning("decisione %s non arrivata ad Agate: %s", approval_id, e)
        raise Rifiutata(f"Il Controllo AI non ha accettato la decisione: {e}. Non è cambiato nulla.") from None


def decidi(utente, tipo, pk, approva, motivo="", password=""):
    """Approva o rifiuta una voce a nome di `utente`. Restituisce il messaggio per la persona; solleva Rifiutata."""
    motivo = (motivo or "").strip()[:1000]
    if tipo == AGENTE and vede_agenti(utente):
        a = _approvazioni().filter(pk=pk).first()
        if a is None:
            raise Rifiutata("Non è più in attesa: forse l'ha già decisa qualcun altro o è scaduta.")
        if approva and irreversibile_agente(a) and not utente.check_password(password or ""):
            raise Rifiutata("Password sbagliata: per approvare un'azione che non si può annullare riscrivi la tua "
                            "password. Non è cambiato nulla.")
        esito = _ad_agate(a.approval_id, approva, utente, motivo)
        if esito == applicazione.IN_CONFERMA:
            a.in_conferma = True
            a.save(update_fields=["in_conferma"])
            return ("Abbiamo mandato un'email di conferma ai responsabili: l'azione parte appena "
                    "confermano.")
        a.stato = "decisa" if esito is None else "approved" if approva else "rejected"
        a.decisa, a.decisa_da, a.motivo = timezone.now(), applicazione.chi(utente), motivo
        a.save(update_fields=["stato", "decisa", "decisa_da", "motivo"])
        if esito is None:
            return "Era già stata decisa."
        return "Approvata: l'agente può procedere." if approva else "Rifiutata: l'agente non lo farà."
    if tipo == ASSISTENTE and vede_assistente(utente):
        v = _valutazioni().select_related("proposta").filter(pk=pk).first()
        if v is None:
            raise Rifiutata("Non è più in attesa: forse l'ha già decisa qualcun altro o è scaduta.")
        if approva and irreversibile_assistente(v) and not utente.check_password(password or ""):
            raise Rifiutata("Password sbagliata: per approvare un'azione che non si può annullare riscrivi la tua "
                            "password. Non è cambiato nulla.")
        esito = _ad_agate(v.approval_id, approva, utente, motivo)
        if esito is None:
            return "Era già stata decisa: l'esito arriva da solo entro un minuto."
        if esito == applicazione.IN_CONFERMA:
            return "Abbiamo mandato un'email di conferma ai responsabili: si esegue appena confermano."
        decisa(v, "approved" if approva else "rejected", applicazione.chi(utente), motivo)
        v.refresh_from_db()
        if approva:
            return f"Approvata ed eseguita: «{v.proposta.titolo}»." if v.stato == Valutazione.APPROVATA else \
                "Approvata."
        return f"Rifiutata: «{v.proposta.titolo}» non si esegue."
    raise Rifiutata("Questa voce non c'è, o non puoi deciderla.")
