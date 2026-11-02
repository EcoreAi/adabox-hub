"""Webhook di Agate: le approvazioni in attesa, da mostrare in «Approvazioni in attesa».

L'azienda registra in Agate (Impostazioni → Webhook) l'indirizzo `{base_url}/awf/agate-webhook/` con gli eventi
`approval.requested` e `approval.decided`, e incolla in «Stato e collegamento» il segreto `whsec_...`.

La firma è quella di Agate (`agategw.contracts.webhooks`), ricalcolata qui byte per byte:
`X-Agate-Signature: t=<unix>,v1=<hmac-sha256 hex di f"{t}.".encode() + corpo>`, confronto a tempo costante,
tolleranza 5 minuti. Qui le approvazioni si registrano e si chiudono; si decidono in «Da approvare» (collegato ad Agate
con un codice: allora l'indirizzo dei webhook è quello del modulo `agate`, che passa qui gli eventi con `gestisci`) o
nella console di Agate. Le approvazioni del contratto le segue la richiesta (`RichiestaAgenti.approval_id`)."""
import hashlib
import hmac
import json
import logging
import re
import time

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from core.cifratura import SegretoIlleggibile

from .models import Approvazione, Collegamento, RichiestaAgenti

log = logging.getLogger("awf.webhook")

INTESTAZIONE = "X-Agate-Signature"
TOLLERANZA = 300
MAX_CORPO = 256_000
MAX_PARAMETRI = 20_000
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class FirmaNonValida(ValueError):
    """Firma assente, malformata, errata o troppo vecchia."""


def _hmac(segreto, t, corpo):
    return hmac.new(segreto.encode(), f"{t}.".encode() + corpo, hashlib.sha256).hexdigest()


def firma(segreto, corpo, t=None):
    """Il valore dell'intestazione per `corpo`, come lo calcola Agate (serve ai test e alle prove a mano)."""
    t = int(time.time()) if t is None else t
    return f"t={t},v1={_hmac(segreto, t, corpo)}"


def verifica(segreto, intestazione, corpo, tolleranza=TOLLERANZA, ora=None):
    """Verifica la firma come `agategw.contracts.webhooks.verify` e restituisce il timestamp firmato."""
    if not intestazione:
        raise FirmaNonValida("firma assente")
    parti = dict(voce.split("=", 1) for voce in intestazione.split(",") if "=" in voce)
    try:
        t = int(parti["t"])
        ricevuta = parti["v1"]
    except (KeyError, ValueError):
        raise FirmaNonValida("firma malformata") from None
    if not ricevuta.isascii():                          # compare_digest rifiuta il non ASCII con TypeError
        raise FirmaNonValida("firma malformata")
    if not hmac.compare_digest(ricevuta, _hmac(segreto, t, corpo)):
        raise FirmaNonValida("firma non valida")
    if abs((int(time.time()) if ora is None else ora) - t) > tolleranza:
        raise FirmaNonValida("firma scaduta")
    return t


@csrf_exempt
def ricevi(request):
    if request.method != "POST":
        risposta = JsonResponse({"error": "usare POST"}, status=405)
        risposta["Allow"] = "POST"
        return risposta
    c = Collegamento.objects.filter(pk=1).first()
    try:
        segreto = c.segreto_webhook() if c is not None else ""
    except SegretoIlleggibile:
        segreto = ""
    if not segreto:
        return JsonResponse({"error": "segreto dei webhook non configurato"}, status=503)
    try:
        dimensione = int(request.headers.get("Content-Length") or 0)
    except ValueError:
        dimensione = 0
    if dimensione > MAX_CORPO:
        return JsonResponse({"error": "corpo troppo grande"}, status=413)
    corpo = request.body
    try:
        verifica(segreto, request.headers.get(INTESTAZIONE), corpo)
    except FirmaNonValida as e:
        return JsonResponse({"error": str(e)}, status=401)
    try:
        evento = json.loads(corpo)
    except ValueError:
        return JsonResponse({"error": "JSON non valido"}, status=400)
    if not isinstance(evento, dict) or not isinstance(evento.get("data"), dict):
        return JsonResponse({"error": "evento non valido"}, status=400)
    return gestisci(evento.get("type"), evento["data"])


def gestisci(tipo, dati):
    """Un evento di Agate già verificato: lo usa anche il webhook del modulo `agate` (un solo indirizzo per
    l'applicazione collegata con un codice), che passa qui le approvazioni che non sono dell'assistente."""
    if tipo == "approval.requested":
        return _richiesta(dati)
    if tipo == "approval.decided":
        return _decisa(dati)
    return JsonResponse({"ok": True, "ignorato": True})


def _id(dati):
    valore = dati.get("approval_id")
    return valore if isinstance(valore, str) and ID_RE.match(valore) else None


def _data(valore):
    try:
        d = parse_datetime(valore) if isinstance(valore, str) else None
    except ValueError:
        return None
    return timezone.make_aware(d) if d is not None and timezone.is_naive(d) else d


def _richiesta(dati):
    approval_id = _id(dati)
    if approval_id is None:
        return JsonResponse({"error": "approval_id mancante o non valido"}, status=400)
    if RichiestaAgenti.objects.filter(approval_id=approval_id).exists():
        return JsonResponse({"ok": True, "contratto": True})       # il contratto lo segue la sua richiesta
    strumento = str(dati.get("tool") or "")[:200]
    contratto = bool(dati.get("engagement_id")) and not strumento    # rinnovo o cambio del contratto
    riepilogo = dati.get("summary")                     # già mascherato da Agate
    if not isinstance(riepilogo, str) or not riepilogo.strip():
        riepilogo = ("Il contratto degli agenti chiede una decisione (rinnovo o modifica)" if contratto else
                     f"Azione {strumento} in attesa di approvazione" if strumento else
                     "Azione in attesa di approvazione")
    valori = {"strumento": strumento, "riepilogo": riepilogo[:2000], "scade": _data(dati.get("expires_at")),
              "contratto": contratto, "parametri": _parametri(dati.get("params")), "attore": _attore(dati)}
    # una consegna ripetuta aggiorna la riga ma non riapre un'approvazione già decisa
    approvazione, creata = Approvazione.objects.get_or_create(approval_id=approval_id, defaults=valori)
    if not creata:
        Approvazione.objects.filter(pk=approvazione.pk).update(**valori)
    return JsonResponse({"ok": True})


def _parametri(valore):
    """I parametri dell'azione, se ci sono (già mascherati da Agate): un oggetto JSON piccolo, o niente."""
    if not isinstance(valore, dict):
        return {}
    try:
        return valore if len(json.dumps(valore, ensure_ascii=False, default=str)) <= MAX_PARAMETRI else {}
    except (TypeError, ValueError):
        return {}


def _attore(dati):
    """Chi chiede, se il webhook lo dice: `actor` ({"id"} o {"name"}), `agent` (testo o come `actor`), `agent_id`."""
    for chiave in ("actor", "agent"):
        valore = dati.get(chiave)
        if isinstance(valore, dict):
            valore = valore.get("name") or valore.get("id")
        if isinstance(valore, str) and valore.strip():
            return valore.strip()[:200]
    valore = dati.get("agent_name") or dati.get("agent_id")
    return valore.strip()[:200] if isinstance(valore, str) else ""


def _decisa(dati):
    approval_id = _id(dati)
    if approval_id is None:
        return JsonResponse({"error": "approval_id mancante o non valido"}, status=400)
    decisione = dati.get("decision")
    stato = decisione[:20] if isinstance(decisione, str) and ID_RE.match(decisione) else "decisa"
    richiesta = RichiestaAgenti.objects.filter(approval_id=approval_id).first()
    if richiesta is not None:                           # il contratto: anche dopo la doppia conferma dei responsabili
        if richiesta.stato == RichiestaAgenti.DA_APPROVARE:
            RichiestaAgenti.objects.filter(pk=richiesta.pk).update(
                decisione=RichiestaAgenti.APPROVATA if stato == "approved" else RichiestaAgenti.RIFIUTATA_QUI,
                decisione_il=timezone.now(), aggiornata=timezone.now())
        return JsonResponse({"ok": True, "contratto": True})
    # se la decisione arriva prima della richiesta (consegne fuori ordine) la riga nasce già chiusa
    Approvazione.objects.update_or_create(approval_id=approval_id,
                                          defaults={"stato": stato, "decisa": timezone.now(), "in_conferma": False})
    return JsonResponse({"ok": True})
