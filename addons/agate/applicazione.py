"""Il percorso semplice (§8 di `docs/plugin-api.md` di agentlia-workforce): Agate resta il garante, ma chi usa adabox
non lo vede mai.

- **Una volta sola, con un codice** (§8.1): chi gestisce Agate dà un codice `agc_`; adabox genera la chiave del suo
  server MCP (quello degli agenti, modulo `awf`), esporta gli strumenti dell'assistente e chiama
  `POST {agate}/v1/apps/connect`. Agate risponde con tre chiavi separate — `evaluate` (l'assistente, come la chiave
  di sempre), `decide` (solo le decisioni delle persone), `sync` (solo risincronizzare gli strumenti) — il segreto
  dei webhook e, se l'azienda lo permette, il codice `agf_` per la fabbrica degli agenti. Le chiavi e il codice si
  salvano cifrati; la protezione diventa «Attiva».
- **Agate incluso** (§8.6): l'azienda che non ha Agate non incolla nessun codice. Alla prima assunzione degli agenti
  la fabbrica apre il suo Agate (ospitato da Agentlia, titolare chi conferma) e restituisce il codice; adabox fa
  subito lo stesso collegamento (`collega(..., incluso=True)`, modulo `awf.assunzione`).
- **Le decisioni** (§8.4) si prendono in adabox, sempre a nome della persona che clicca (`decided_by`
  «Nome Cognome <email>»): il contratto degli agenti, le loro azioni, le proposte dell'assistente in attesa.
- **La risincronizzazione** (§8.1): dopo ogni cambio di «cosa può fare» degli agenti adabox chiede ad Agate di
  rileggere i suoi strumenti. Se non riesce non blocca nessuno: si riprova da sola ogni minuto (lavoro
  «Esito delle approvazioni in Agate»).

Un solo indirizzo per i webhook di Agate: quello di questo modulo (`/agate/webhook/`), che passa ad `awf` le
approvazioni degli agenti."""
import logging
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core import cifratura

from . import cliente
from .models import Collegamento

log = logging.getLogger("agate.applicazione")

NOME_APP = "adabox-hub"
PREFISSO_APP = "awf"                                    # il prefisso degli strumenti degli agenti in Agate
CODICE_RE = re.compile(r"^agc_[A-Za-z0-9_-]{32}$")
DECISA, IN_CONFERMA = "decisa", "in_conferma"


class ErroreCollegamento(Exception):
    """Il collegamento con il codice non è riuscito. Il messaggio è per le persone; `stato` è quello HTTP di Agate,
    se ha risposto."""

    def __init__(self, messaggio, stato=None):
        super().__init__(messaggio)
        self.stato = stato


def awf_attivo():
    from core.registry.modules import disattivati
    return "awf" in settings.ADDONS_ATTIVI and "awf" not in disattivati()


def attuale():
    return Collegamento.attuale()


def semplice(c=None):
    """adabox è collegato con il codice: decide qui, a nome di chi clicca."""
    c = c if c is not None else Collegamento.attuale()
    return c is not None and c.puo_decidere and bool(c.gateway_url)


def chi(utente):
    """«Mario Rossi <mario@rossi.it>»: la persona a nome della quale si decide."""
    nome = " ".join((utente.get_full_name() or utente.get_username()).split())
    testo = f"{nome} <{utente.email}>" if getattr(utente, "email", "") else nome
    return testo if len(testo) <= 200 else nome[:200]           # Agate: al più 200 caratteri, mai vuoto


def motivo(quando=None, azione="Confermato"):
    """«Confermato in adabox il 01/11 alle 10:02»."""
    quando = timezone.localtime(quando or timezone.now())
    return f"{azione} in adabox il {quando:%d/%m} alle {quando:%H:%M}"


def strumenti_interni(c=None):
    """Gli strumenti di scrittura dell'assistente (T127), con il prefisso di questo collegamento."""
    from .management.commands.agate_strumenti import definizioni
    c = c if c is not None else Collegamento.attuale()
    return definizioni(c.prefisso if c is not None else "adabox")


def controlla_url(valore, cosa):
    valore = (valore or "").strip().rstrip("/")
    parti = urlsplit(valore)
    ammessi = ("https", "http") if settings.DEBUG else ("https",)
    if parti.scheme not in ammessi or not parti.netloc or parti.query or parti.fragment:
        raise ErroreCollegamento(f"L'indirizzo {cosa} non è valido: serve https://… (per esempio "
                                 f"https://agate.tuaazienda.it).")
    return valore


def _messaggio(e, mcp_url):
    if e.stato == 404:
        return ("Il codice non esiste o è scaduto (vale 7 giorni): chiedine uno nuovo a chi gestisce il Controllo "
                "AI.")
    if e.stato == 409:
        return "Questo codice è già stato usato: ne serve uno nuovo."
    if e.stato == 422:
        testo = "Il collegamento non è stato accettato" + (f": {e.dettaglio}" if e.dettaglio else "") + "."
        if "prefix" in e.dettaglio:
            testo += (f" In Agate, quando crei il codice, il prefisso deve essere «{PREFISSO_APP}» e non deve esserci "
                      "già un'applicazione collegata con lo stesso prefisso.")
        return testo
    if e.stato == 429:
        return "Troppi tentativi in poco tempo: riprova tra un minuto."
    if e.stato == 502:
        return (f"Agate non riesce a raggiungere adabox all'indirizzo {mcp_url}: controlla che adabox sia "
                "raggiungibile da internet e riprova. Il codice vale ancora.")
    if e.stato is None:
        return "Agate non risponde a questo indirizzo: controllalo e riprova. Il codice vale ancora."
    return f"Risposta inattesa di Agate (HTTP {e.stato}). Il codice vale ancora: riprova tra poco."


def _testo(risposta, chiave):
    valore = risposta.get(chiave)
    return valore.strip() if isinstance(valore, str) else ""


def collega(gateway_url, codice, base_url, incluso=False):
    """Collega adabox ad Agate con il codice `agc_` (§8.1). Restituisce il `Collegamento` attivo. Solleva
    ErroreCollegamento con un messaggio per le persone; se non riesce, non cambia nulla (nemmeno la chiave del
    server MCP già data ad Agate a mano). `incluso`: il codice è quello dell'Agate appena aperto da Agentlia (§8.6);
    ricollegarsi con un codice allo stesso Agate lo lascia incluso."""
    if not awf_attivo():
        raise ErroreCollegamento("Serve anche il modulo «Agenti AI» (awf): è lui che dà ad Agate gli strumenti "
                                 "degli agenti.")
    from awf import fabbrica
    from awf.models import Collegamento as CollegamentoAwf

    codice = (codice or "").strip()
    if not CODICE_RE.match(codice):
        raise ErroreCollegamento("Il codice non è valido: inizia con agc_ ed è lungo 36 caratteri. Copialo di nuovo "
                                 "da Agate.")
    gateway = controlla_url(gateway_url, "di Agate")
    base = controlla_url(base_url, "di adabox")
    a = CollegamentoAwf.attuale()
    prima = {"base_url": a.base_url, "mcp_impronta": a.mcp_impronta, "mcp_indizio": a.mcp_indizio}
    bearer = fabbrica.nuovo_bearer()
    # la chiave nuova vale subito (salvata, fuori da transazioni): durante la chiamata Agate legge tools/list
    a.base_url, a.mcp_impronta, a.mcp_indizio = base, fabbrica.impronta(bearer), bearer[:8]
    a.save(update_fields=list(prima))
    c = Collegamento.attuale()
    app = {"name": NOME_APP, "prefix": PREFISSO_APP, "mcp_url": a.mcp_url, "mcp_bearer": bearer,
           "webhook_url": base + reverse("agate:webhook"), "internal_tools": strumenti_interni(c)}
    try:
        risposta = cliente.connetti(gateway, codice, app)
        chiavi = risposta.get("keys") if isinstance(risposta.get("keys"), dict) else {}
        if not all(isinstance(chiavi.get(k), str) and chiavi[k] for k in ("evaluate", "decide", "sync")):
            raise cliente.ErroreAgate("risposta senza le tre chiavi", 0)
    except cliente.ErroreAgate as e:
        for campo, valore in prima.items():
            setattr(a, campo, valore)
        a.save(update_fields=list(prima))
        log.warning("collegamento con il codice non riuscito: %s", e)
        if e.stato == 0:
            raise ErroreCollegamento("Agate ha risposto in modo inatteso (mancano le chiavi): riprova tra poco o "
                                     "chiedi a chi gestisce il Controllo AI.", 0) from None
        raise ErroreCollegamento(_messaggio(e, a.mcp_url), e.stato) from None
    console = _testo(risposta, "console_url")
    with transaction.atomic():
        c = c or Collegamento(prefisso="adabox")
        c.incluso = incluso or (c.incluso and c.gateway_url == gateway)
        c.gateway_url = gateway
        if console.startswith(("https://", "http://")):
            c.console_url = console.rstrip("/")
        c.imposta_chiave(chiavi["evaluate"])
        c.chiave_decide_cifrata = cifratura.cifra(chiavi["decide"])
        c.chiave_sync_cifrata = cifratura.cifra(chiavi["sync"])
        if segreto := _testo(risposta, "webhook_secret"):
            c.imposta_segreto(segreto)
        c.tenant = _testo(risposta, "tenant")[:200]
        c.modalita = Collegamento.ATTIVO
        c.con_codice_il = c.ultimo_controllo = c.sincronizzato_il = timezone.now()
        strumenti = risposta.get("tools") if isinstance(risposta.get("tools"), dict) else {}
        c.esito_controllo = (f"Agate risponde: collegato con un codice ({strumenti.get('enabled', 0)} strumenti "
                             "attivi)")[:300]
        c.da_sincronizzare, c.esito_sincronizzazione = False, ""
        c.save()
        fattoria = _testo(risposta, "factory_code")
        a.factory_code_cifrato = cifratura.cifra(fattoria) if fattoria else ""
        if not a.agate_url and c.console_url:
            a.agate_url = c.console_url
        a.save(update_fields=["factory_code_cifrato", "agate_url"])
    log.info("adabox collegato ad Agate con un codice (%s)", c.tenant or gateway)
    return c


def decidi(approval_id, decisione, utente, motivo_testo="", c=None):
    """Decide un'approvazione in Agate a nome di `utente` (§8.4). `decisione`: "approved" | "rejected".
    Restituisce DECISA (200) o IN_CONFERMA (202, doppia conferma: Agate ha scritto ai responsabili). Solleva
    ErroreCollegamento senza la chiave `decide`, cliente.ErroreAgate se Agate rifiuta o non risponde."""
    c = c if c is not None else Collegamento.attuale()
    if not semplice(c):
        raise ErroreCollegamento("Le decisioni si prendono in Agate: adabox non è collegato con un codice.")
    stato, risposta = cliente.decidi(c, approval_id, decisione, chi(utente), motivo_testo)
    if stato == 202 or risposta.get("status") == "awaiting_confirmation":
        return IN_CONFERMA
    return DECISA


def sincronizza(c=None):
    """Chiede ad Agate di rileggere gli strumenti di adabox (dopo un cambio di «cosa può fare»). Non solleva mai:
    se non riesce lo segna e il lavoro di ogni minuto riprova. True se riuscita (o se non serve: niente chiave)."""
    c = c if c is not None else Collegamento.attuale()
    if c is None or not c.chiave_sync_cifrata:
        return True
    try:
        risposta = cliente.sincronizza(c, strumenti_interni(c))
    except (cliente.ErroreAgate, cifratura.SegretoIlleggibile) as e:
        log.warning("risincronizzazione degli strumenti non riuscita: %s", e)
        c.da_sincronizzare, c.esito_sincronizzazione = True, f"non riuscita: {e}"[:300]
        c.save(update_fields=["da_sincronizzare", "esito_sincronizzazione"])
        return False
    c.da_sincronizzare, c.sincronizzato_il = False, timezone.now()
    c.esito_sincronizzazione = (f"nuovi {risposta.get('imported', 0)}, aggiornati {risposta.get('updated', 0)}, "
                                f"spenti {risposta.get('disabled', 0)}")[:300]
    c.save(update_fields=["da_sincronizzare", "sincronizzato_il", "esito_sincronizzazione"])
    return True


def sincronizza_dopo_il_commit():
    """Agate rilegge `tools/list` di adabox con un'altra richiesta: le operazioni ammesse devono essere già salvate."""
    transaction.on_commit(sincronizza)
