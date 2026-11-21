"""Il gateway dei modelli (LiteLLM): le chiavi vere dei fornitori stanno solo lì, e ogni istanza riceve una chiave
virtuale sua, con il tetto di spesa del suo piano e i soli modelli che vendiamo. Così la chiave vera non arriva mai
su un server che non è nostro, una chiave si blocca senza toccare gli altri clienti, e il tetto vale anche se
un'istanza sul server del cliente viene manomessa.

Il portale parla con l'API di gestione di LiteLLM (`/key/generate`, `/key/update`, `/key/block`, `/key/unblock`,
`/key/delete`) con la chiave principale, che resta nel suo `.env`:
- RIVENDITA_GATEWAY_URL: dove il portale raggiunge il gateway (es. http://adabox_gateway:4000);
- RIVENDITA_GATEWAY_CHIAVE: la chiave principale di LiteLLM (LITELLM_MASTER_KEY);
- RIVENDITA_GATEWAY_URL_ISTANZE: l'indirizzo con cui lo raggiungono le istanze, se diverso (es. https://ai.ichnobyte.it).

Passano dal gateway i «Provider AI forniti» segnati «passa dal gateway». Le istanze li usano come sempre: con il tipo
Anthropic chiamano `<gateway>/v1/messages`, con quelli OpenAI `<gateway>/v1/chat/completions`; l'ID di ogni modello
deve essere il `model_name` scritto nella configurazione di LiteLLM (deploy/gateway.config.yaml).
Il tetto della chiave è mensile (`budget_duration` 30d: LiteLLM lo azzera il primo del mese) e segue la formula:
quota con «inclusa», tetto massimo con «a consumo», tetto con «mista»; senza valore la chiave non ha tetto."""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from core import cifratura

from . import servizi
from .models import AI_CONSUMO, AI_INCLUSA, AI_MISTA, AI_PROPRIA, Istanza, ModelloFornito

log = logging.getLogger("rivendita.gateway")
TIMEOUT = 20
MENSILE = "30d"
TIPI = ("anthropic", "openai", "openai_compat")          # i formati che il gateway espone alle istanze


class GatewayNonRisponde(Exception):
    """Gateway irraggiungibile o risposta non valida: resta tutto com'è, si riprova al prossimo giro."""


def configurato():
    return bool(settings.RIVENDITA_GATEWAY_URL and settings.RIVENDITA_GATEWAY_CHIAVE)


def url_per(tipo):
    """L'indirizzo che un'istanza usa per un provider di questo tipo."""
    base = (settings.RIVENDITA_GATEWAY_URL_ISTANZE or settings.RIVENDITA_GATEWAY_URL).rstrip("/")
    return base if tipo == "anthropic" else f"{base}/v1"


def _chiama(percorso, dati):
    richiesta = urllib.request.Request(
        f"{settings.RIVENDITA_GATEWAY_URL.rstrip('/')}/{percorso}", data=json.dumps(dati).encode(), method="POST",
        headers={"Authorization": f"Bearer {settings.RIVENDITA_GATEWAY_CHIAVE}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            return json.loads(risposta.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise GatewayNonRisponde(f"il gateway ha risposto {e.code} a {percorso}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise GatewayNonRisponde(f"gateway non raggiungibile: {e}") from e


def alias(istanza):
    return f"adabox-{istanza.codice}"


def tetto(istanza):
    """Il tetto mensile della chiave in dollari, o None se la formula non ne ha uno."""
    termini = istanza.termini_ai()
    valore = {AI_INCLUSA: servizi.quota_ai(istanza, termini), AI_CONSUMO: termini["quota_istanza"],
              AI_MISTA: termini["tetto_istanza"]}.get(termini["formula"])
    return float(valore) if valore else None


def voluto(istanza):
    """Che cosa deve valere per la chiave dell'istanza: {"max_budget", "models"}; None se non deve poterla usare
    (istanza spenta, chiave del cliente, o nessun modello che passa dal gateway)."""
    if not istanza.attiva or istanza.termini_ai()["formula"] == AI_PROPRIA:
        return None
    modelli = sorted(set(ModelloFornito.objects.filter(attivo=True, provider__attivo=True, provider__via_gateway=True).values_list("id_api", flat=True)))
    return {"max_budget": tetto(istanza), "models": modelli} if modelli else None


def _chiave(istanza):
    try:
        return cifratura.decifra(istanza.gateway_chiave_cifrata) if istanza.gateway_chiave_cifrata else ""
    except cifratura.SegretoIlleggibile:
        return ""


def _salva(istanza, **campi):
    for nome, valore in campi.items():
        setattr(istanza, nome, valore)
    Istanza.objects.filter(pk=istanza.pk).update(**campi)


def _genera(istanza, serve):
    risposta = _chiama("key/generate", {"key_alias": alias(istanza), "metadata": {"cliente": istanza.cliente, "istanza": str(istanza.codice)},
                                        "budget_duration": MENSILE, **serve})
    chiave = risposta.get("key") if isinstance(risposta, dict) else None
    if not isinstance(chiave, str) or not chiave:
        raise GatewayNonRisponde("il gateway non ha restituito la chiave")
    _salva(istanza, gateway_chiave_cifrata=cifratura.cifra(chiave), gateway_stato={**serve, "bloccata": False})
    return chiave


def allinea(istanza):
    """Porta la chiave virtuale dell'istanza a ciò che le spetta: la crea se manca, ne aggiorna tetto e modelli se sono
    cambiati, la blocca se l'istanza non deve più usarla e la sblocca se torna a poterlo. Parla con il gateway solo se
    c'è qualcosa da cambiare. Restituisce la chiave in chiaro, o "" se l'istanza non ne ha una utilizzabile.
    GatewayNonRisponde se il gateway non risponde."""
    if not configurato():
        return ""
    chiave, serve, stato = _chiave(istanza), voluto(istanza), dict(istanza.gateway_stato or {})
    if serve is None:
        if chiave and not stato.get("bloccata"):
            _chiama("key/block", {"key": chiave})
            _salva(istanza, gateway_stato={**stato, "bloccata": True})
        return ""
    if not chiave:
        return _genera(istanza, serve)
    if stato.get("bloccata"):
        _chiama("key/unblock", {"key": chiave})
        stato["bloccata"] = False
        _salva(istanza, gateway_stato=stato)
    if {nome: stato.get(nome) for nome in serve} != serve:
        _chiama("key/update", {"key": chiave, "budget_duration": MENSILE, **serve})
        _salva(istanza, gateway_stato={**stato, **serve})
    return chiave


def chiave_per(istanza):
    """La chiave virtuale per la configurazione che va all'istanza; "" se non c'è o il gateway non risponde (l'istanza
    tiene ciò che aveva e riprova tra un'ora)."""
    try:
        return allinea(istanza)
    except GatewayNonRisponde as e:
        log.warning("chiave del gateway per %s: %s", istanza, e)
        return ""


def rigenera(istanza):
    """Butta la chiave virtuale dell'istanza e ne crea una nuova (chiave finita in mani sbagliate): quella di prima
    smette subito di funzionare, la nuova arriva all'istanza alla prossima sincronizzazione."""
    if not configurato():
        raise GatewayNonRisponde("il gateway non è configurato (RIVENDITA_GATEWAY_URL e RIVENDITA_GATEWAY_CHIAVE)")
    serve = voluto(istanza)
    if serve is None:
        raise GatewayNonRisponde("questa istanza non usa modelli che passano dal gateway")
    if vecchia := _chiave(istanza):
        _chiama("key/delete", {"keys": [vecchia]})
    _salva(istanza, gateway_chiave_cifrata="", gateway_stato={})
    return _genera(istanza, serve)


def giro():
    """Voce `cron` del manifest, ogni ora: allinea le chiavi di tutte le istanze, anche di quelle spente (che non
    chiamano più il portale: è qui che la loro chiave si blocca). None se il gateway non è configurato."""
    if not configurato():
        return None
    fatte, errori = 0, 0
    for istanza in Istanza.objects.select_related("piano"):
        try:
            allinea(istanza)
            fatte += 1
        except GatewayNonRisponde as e:
            errori += 1
            log.warning("chiave del gateway per %s: %s", istanza, e)
    return f"chiavi allineate: {fatte}" + (f", non riuscite: {errori}" if errori else "")


giro.senza_transazione = True      # chiamate di rete: ogni istanza salva per conto suo
