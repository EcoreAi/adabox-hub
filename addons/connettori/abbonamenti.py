"""Abbonamenti ai webhook via API, per le piattaforme di automazione (Zapier, Make, n8n): quando qualcuno accende un
flusso là, la piattaforma chiede ad adabox di avvisarla a un suo indirizzo, e quando lo spegne lo toglie. È lo
schema «REST hook»; i dati che arrivano sono gli stessi dei webhook scritti a mano (connettori.consegne).

    GET    /connettori/api/eventi/               gli eventi a cui ci si può abbonare, con l'elenco da cui leggere esempi
    POST   /connettori/api/abbonamenti/          {"url": "https://…", "eventi": ["contatti.contatto.creato"], "nome": "…"}
    DELETE /connettori/api/abbonamenti/<id>/

Si entra solo con un token API (Authorization: Bearer …, creato dal profilo), che deve valere per il modulo
`connettori` e non essere in sola lettura; chi lo ha creato deve poter aggiungere webhook. L'azienda è quella del
token, o `X-Azienda`. Da qui si tolgono solo gli abbonamenti nati da qui: i webhook scritti a mano non si toccano."""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods
from ninja.errors import HttpError

from core import registro
from core.api.auth import azienda_per
from core.models import TokenApi
from core.viste import registry

from . import eventi
from .models import Webhook

AZIONI = (("creato", "creato"), ("aggiornato", "modificato"), ("eliminato", "eliminato"))
MAX_ABBONAMENTI = 200                                  # per azienda: un flusso impazzito non ne crea all'infinito


class Rifiuto(Exception):
    def __init__(self, stato, messaggio):
        self.stato, self.messaggio = stato, messaggio


def _entra(request, scrittura):
    """Utente e azienda dal token; Rifiuto se il token non c'è o non basta."""
    intestazione = request.headers.get("Authorization", "")
    token = TokenApi.verifica(intestazione[7:].strip()) if intestazione.startswith("Bearer ") else None
    if token is None:
        raise Rifiuto(401, "token API mancante o non valido")
    request.user, request.token_api = token.utente, token
    registro.imposta(token.utente, "api")
    if not token.permette("connettori", scrittura):
        raise Rifiuto(403, "questo token è in sola lettura" if scrittura and token.sola_lettura else "questo token non vale per il modulo connettori")
    try:
        azienda = azienda_per(request)
    except HttpError as e:
        raise Rifiuto(403, str(e)) from e
    if azienda is None:
        raise Rifiuto(403, "nessuna azienda per questo utente")
    return azienda


def _protetta(scrittura):
    def decora(funzione):
        def vista(request, *args, **kwargs):
            try:
                return funzione(request, _entra(request, scrittura), *args, **kwargs)
            except Rifiuto as e:
                return JsonResponse({"detail": e.messaggio}, status=e.stato)
        return csrf_exempt(vista)
    return decora


def eventi_per(request):
    """Gli eventi a cui chi chiama può abbonarsi: i record delle viste aperte all'API, per azienda, che può vedere."""
    voci = []
    for modulo in sorted(registry._viste):
        for vista in registry.viste_di(modulo):
            if not (vista.api and vista.company_field and vista.has_view_permission(request)):
                continue
            for azione, parola in AZIONI:
                voci.append({"evento": eventi.nome_evento(vista.model, azione), "nome": f"{str(vista.verbose_name).capitalize()} {parola}",
                             "lista": f"/api/v1/{vista.modulo}/{vista.slug}/"})
    return voci


@require_GET
@_protetta(scrittura=False)
def elenco_eventi(request, azienda):
    return JsonResponse({"eventi": eventi_per(request)})


@require_http_methods(["POST"])
@_protetta(scrittura=True)
def abbona(request, azienda):
    if not request.user.has_perm("connettori.add_webhook"):
        raise Rifiuto(403, "serve il permesso di aggiungere webhook")
    try:
        dati = json.loads(request.body or b"{}")
    except ValueError:
        dati = None
    if not isinstance(dati, dict) or not isinstance(dati.get("url"), str):
        raise Rifiuto(400, "serve un corpo JSON con «url» ed «eventi»")
    voci = dati.get("eventi")
    voci = [voci] if isinstance(voci, str) else voci
    if not isinstance(voci, list) or not voci or not all(isinstance(v, str) for v in voci):
        raise Rifiuto(400, "«eventi» è un elenco di nomi, es. [\"contatti.contatto.creato\"]")
    ammessi = {v["evento"] for v in eventi_per(request)}
    if fuori := [v for v in voci if v not in ammessi]:      # niente caratteri jolly da qui: solo ciò che chi chiama può vedere
        raise Rifiuto(400, f"eventi non disponibili: {', '.join(fuori)[:200]}")
    if Webhook.objects.filter(azienda=azienda, da_api=True).count() >= MAX_ABBONAMENTI:
        raise Rifiuto(409, f"troppi abbonamenti aperti ({MAX_ABBONAMENTI}): toglierne qualcuno da Connettori → Webhook")
    webhook = Webhook(azienda=azienda, nome=str(dati.get("nome") or "Automazione esterna")[:80], url=dati["url"], eventi="\n".join(voci), da_api=True)
    from django.core.exceptions import ValidationError
    try:
        webhook.full_clean(exclude=["segreto_cifrato"])
    except ValidationError as e:
        raise Rifiuto(400, "; ".join(m for messaggi in e.message_dict.values() for m in messaggi)[:300]) from e
    webhook.save()
    return JsonResponse({"id": webhook.pk, "eventi": voci, "segreto": webhook.segreto()}, status=201)


@require_http_methods(["DELETE"])
@_protetta(scrittura=True)
def disdici(request, azienda, pk):
    if not request.user.has_perm("connettori.delete_webhook"):
        raise Rifiuto(403, "serve il permesso di eliminare webhook")
    Webhook.objects.filter(pk=pk, azienda=azienda, da_api=True).delete()        # già tolto: va bene lo stesso
    return JsonResponse({}, status=200)
