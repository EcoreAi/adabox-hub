"""«Assumi»: chiedere un agente del negozio da una pagina sola, già compilata con valori prudenti (4 settimane,
responsabile chi chiede, nessuna persona, cosa può fare con le scelte proposte), e l'invio della richiesta. Chi
vuole cambia tutto in «Personalizza», sulla stessa pagina: niente bozze in sessione né righe a metà nel database.

All'invio adabox si prepara da solo: ammette le operazioni scelte («Sì» e «Con il tuo ok»; «Mai»
no) **prima** di chiedere la squadra, nella stessa transazione, così la richiesta dichiara alla fabbrica le
operazioni che gli agenti useranno (§7.2: `plugin.operations` sono quelle ammesse ora). Se la fabbrica rifiuta, non
resta ammesso nulla.

«Con il tuo ok» per ora vale come «Sì» qui: la conferma di una persona la chiedono le regole di Agate (le imposta
chi gestisce Agate). La scelta resta salvata nella richiesta per quando le regole nasceranno da sole."""
import logging

from django.db import transaction

from . import contratto, fabbrica, operazioni, squadre
from .models import Collegamento, OperazioneAmmessa

log = logging.getLogger("awf.assunzione")

SETTIMANE = 4                                           # la durata proposta
MAX_NOTE = 700                                          # il resto delle 1000 del contratto è per la riga sulle persone


def persone_possibili():
    """Le persone attive di adabox: mai gli utenti agente né i clienti del portale."""
    from django.contrib.auth import get_user_model
    return (get_user_model().objects.filter(is_active=True, agente_awf__isnull=True)
            .exclude(profilo__esterno=True).order_by("first_name", "last_name", "username"))


def reparti_suggeriti(azienda=None):
    """I reparti dell'app Personale, se è installata e accesa, come suggerimenti; altrimenti nessuno."""
    from django.conf import settings
    from core.registry.modules import disattivati
    if "personale" not in settings.ADDONS_ATTIVI or "personale" in disattivati():
        return []
    try:
        from personale.models import Reparto
        reparti = Reparto.objects.all()
        if azienda is not None:
            reparti = reparti.filter(azienda=azienda)
        return list(dict.fromkeys(reparti.values_list("nome", flat=True)[:50]))
    except Exception:                                   # app non migrata o cambiata: solo testo libero
        log.warning("reparti di Personale non leggibili", exc_info=True)
        return []


def invia(team, versione, settimane, note="", utente=None, azienda=None, base_url="", scelte=None, reparto="",
          responsabile=None, persone=(), consenso=None):
    """Prepara adabox e chiede la squadra alla fabbrica (§7.2, contratto invariato). Senza `scelte` valgono quelle
    proposte (letture e modifiche sì, irreversibili con il tuo ok: tutte ammesse). Nelle note per Agentlia va anche
    una riga su per chi lavorano gli agenti (solo i nomi). `consenso` è quello che la persona ha confermato con la
    password (`contratto.consenso`): se il contratto proposto combacia, adabox lo approva a suo nome. Dopo l'invio
    Agate rilegge gli strumenti di adabox (§8.1). Restituisce la `RichiestaAgenti`."""
    s = fabbrica.squadra(team)
    if s is None:
        raise fabbrica.ErroreFabbrica("squadra sconosciuta o non più in catalogo", 404)
    righe = squadre.righe_operazioni(s["operazioni"])
    scelte = squadre.scelte(righe, scelte)
    persone = list(persone)
    testo = "\n".join(x for x in ((note or "").strip(), squadre.riga_persone(reparto, responsabile, persone)) if x)
    # prima le operazioni, salvate, e Agate che le rilegge: la fabbrica propone subito il contratto e Agate lo
    # accetta solo se gli strumenti della squadra sono già attivi (§8.3). Se la fabbrica rifiuta si torna indietro.
    with transaction.atomic():
        nuove, spente = squadre.applica(righe, scelte, utente)
    contratto.sincronizza()
    try:
        with transaction.atomic():
            r = fabbrica.richiedi(team, versione, settimane, testo, utente, azienda, base_url=base_url)
            r.reparto_azienda, r.responsabile, r.scelte = (reparto or "")[:80], responsabile, scelte
            r.consenso = consenso or {}
            r.save(update_fields=["reparto_azienda", "responsabile", "scelte", "consenso"])
            if persone:
                r.persone.set(persone)
    except Exception:
        _annulla(nuove, spente)
        contratto.sincronizza()
        raise
    c = Collegamento.attuale()
    if not c.base_url:                                  # l'indirizzo per Agate (server MCP) si vede in Avanzate
        c.base_url = r.base_url
        c.save(update_fields=["base_url"])
    if c.collegato:
        try:
            fabbrica.battito()                          # la versione dichiarata cambia con l'elenco
        except fabbrica.ErroreFabbrica:
            pass
    return r


def _annulla(nuove, spente):
    """Rimette le operazioni come prima di `squadre.applica`: le ammesse ora si spengono (create ora: si tolgono)."""
    with transaction.atomic():
        for x in nuove:
            voci = OperazioneAmmessa.objects.filter(strumento=x["strumento"], vista=x["vista"])
            voci.update(attiva=False) if x["esiste"] else voci.delete()
        for x in spente:
            OperazioneAmmessa.objects.filter(strumento=x["strumento"], vista=x["vista"]).update(attiva=True)
        operazioni.allinea_gruppo()


def salva_scelte(richiesta, dati, utente=None):
    """«Cosa può fare» cambiato da I miei agenti: salva le scelte e riallinea le operazioni ammesse."""
    righe = squadre.stato_operazioni(richiesta)
    richiesta.scelte = squadre.scelte(righe, dati)
    richiesta.save(update_fields=["scelte", "aggiornata"])
    nuove, spente = squadre.applica(righe, richiesta.scelte, utente)
    contratto.sincronizza()
    if Collegamento.attuale().collegato:
        try:
            fabbrica.battito()
        except fabbrica.ErroreFabbrica:
            pass
    return nuove, spente
