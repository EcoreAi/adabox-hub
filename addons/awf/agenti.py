"""Utenti agente: chi sono, come si creano, chi agisce in una chiamata MCP e come restano fuori dall'interfaccia.

Ogni agente dell'ingaggio ha un utente Django `awf-<nome>` (l'agente tecnico `awf-tecnico`): **attivo**, perché le
`ModelView` controllano i permessi solo agli utenti attivi, ma con la password inutilizzabile, senza email, mai staff
né superuser. Un utente agente non entra mai nell'interfaccia:

- la password inutilizzabile fa fallire ogni accesso con utente e password, e senza email non c'è recupero;
- se un altro backend o un amministratore lo facesse entrare comunque, il segnale `user_logged_in` (vedi
  `accesso_negato`) svuota la sessione e risponde 403: vale per qualunque backend che passi da
  `django.contrib.auth.login`, senza toccare i middleware del kernel;
- non può avere token API (`TokenApi`): si cancellano a ogni allineamento e un nuovo token si rifiuta.

I permessi di un agente vengono **solo** dal gruppo «AWF / Agenti», ricalcolato dalle operazioni ammesse
(`operazioni.allinea_gruppo`). A ogni chiamata `confina` rimette gruppi e permessi com'erano: se l'hook di un'altra
app ha messo gli agenti nei suoi gruppi («tutti gli utenti attivi»), alla chiamata successiva ne escono.

Identità in una chiamata: Agate si collega con un solo bearer, quindi chi agisce si legge dalla chiamata, in
quest'ordine: `_meta["agentlia/agent"]`, `_meta["agent"]`, l'argomento `agente` (o `agent`), altrimenti l'agente
tecnico. Il nome si cerca per id di Agate, poi per nome, poi per username; un nome che non corrisponde a un agente
attivo è un errore, non si ripiega sul tecnico. Non si usa mai l'utente di una persona."""
import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify

from .models import Agente

log = logging.getLogger("awf.agenti")

GRUPPO = "AWF / Agenti"
PREFISSO = "awf-"
TECNICO = "awf-tecnico"


class AgenteSconosciuto(Exception):
    """L'agente indicato non esiste, non è attivo nell'ingaggio o il nome appartiene a una persona."""


def e_agente(utente):
    """Vero se l'utente è un utente agente."""
    if utente is None or not getattr(utente, "pk", None):
        return False
    return Agente.objects.filter(utente_id=utente.pk).exists()


def gruppo():
    return Group.objects.get_or_create(name=GRUPPO)[0]


def username_per(nome):
    return f"{PREFISSO}{slugify(nome) or 'agente'}"[:150]


def assicura(nome, ruolo="", agate_agent_id="", tecnico=False, azienda=None):
    """L'agente con questo nome, creato con il suo utente se manca. Se lo username appartiene a una persona (un
    utente senza scheda agente) si ferma: una persona non diventa mai un agente."""
    username = TECNICO if tecnico else username_per(nome)
    Utente = get_user_model()
    with transaction.atomic():
        utente = Utente.objects.filter(username=username).first()
        if utente is None:
            utente = Utente(username=username, first_name=nome[:150], email="", is_active=True)
            utente.set_unusable_password()
            utente.save()
            agente = Agente.objects.create(utente=utente, nome=nome[:100], ruolo=ruolo[:100],
                                           agate_agent_id=agate_agent_id[:100], tecnico=tecnico)
        else:
            agente = Agente.objects.filter(utente=utente).first()
            if agente is None:
                raise AgenteSconosciuto(f"l'utente {username} esiste ed è una persona, non un agente")
            cambi = {k: v for k, v in {"nome": nome[:100], "ruolo": ruolo[:100],
                                       "agate_agent_id": agate_agent_id[:100]}.items() if v and getattr(agente, k) != v}
            if not agente.attivo:
                cambi["attivo"] = True
            if cambi:
                for k, v in cambi.items():
                    setattr(agente, k, v)
                agente.save(update_fields=list(cambi))
        confina(agente, azienda)
    return agente


def tecnico(azienda=None):
    return assicura("Agente tecnico", ruolo="tecnico", tecnico=True, azienda=azienda)


def confina(agente, azienda=None):
    """Rimette l'utente agente nei suoi confini: attivo, niente password usabile, niente email, niente staff,
    solo il gruppo «AWF / Agenti», nessun permesso diretto, nessun token API, la sola azienda degli agenti.
    Scrive solo quello che è cambiato (a ogni chiamata costa poche letture)."""
    from core.models import ProfiloUtente, TokenApi
    utente = agente.utente
    campi = []
    for campo, valore in (("is_active", True), ("is_staff", False), ("is_superuser", False), ("email", "")):
        if getattr(utente, campo) != valore:
            setattr(utente, campo, valore)
            campi.append(campo)
    if utente.has_usable_password():
        utente.set_unusable_password()
        campi.append("password")
    if campi:
        utente.save(update_fields=campi)
        log.warning("utente agente %s riallineato (%s)", utente.username, ", ".join(campi))
    g = gruppo()
    if list(utente.groups.values_list("pk", flat=True)) != [g.pk]:
        utente.groups.set([g])
    if utente.user_permissions.exists():
        utente.user_permissions.clear()
    TokenApi.objects.filter(utente=utente).delete()
    profilo, _ = ProfiloUtente.objects.get_or_create(utente=utente)
    voluti = [azienda.pk] if azienda is not None else []
    if sorted(profilo.aziende.values_list("pk", flat=True)) != voluti:
        profilo.aziende.set(voluti)
    if profilo.azienda_predefinita_id != (azienda.pk if azienda else None) or profilo.esterno:
        profilo.azienda_predefinita, profilo.esterno = azienda, False
        profilo.save(update_fields=["azienda_predefinita", "esterno"])
    for cache in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        utente.__dict__.pop(cache, None)
    return agente


def risolvi(nome, azienda=None):
    """L'agente che agisce in una chiamata: quello indicato (attivo nell'ingaggio) o il tecnico."""
    if not nome:
        return tecnico(azienda)
    agenti = Agente.objects.select_related("utente")
    for filtro in (Q(agate_agent_id=nome), Q(nome__iexact=nome), Q(utente__username=nome)):
        agente = agenti.filter(filtro).order_by("pk").first()
        if agente is not None:
            break
    else:
        raise AgenteSconosciuto("agente sconosciuto")
    if not agente.attivo and not agente.tecnico:
        raise AgenteSconosciuto("agente non più attivo nell'ingaggio")
    return agente


def sincronizza(ingaggio, azienda=None):
    """Crea o aggiorna un agente per ogni agente dell'ingaggio (§3 del contratto). Chi non è più elencato resta
    come utente (le sue azioni passate restano sue) ma diventa non attivo: le sue chiamate si rifiutano."""
    elenco = ingaggio.get("agents") if isinstance(ingaggio, dict) else None
    if not isinstance(elenco, list):
        return []
    presenti = []
    for voce in elenco:
        if not isinstance(voce, dict) or not isinstance(voce.get("name"), str) or not voce["name"].strip():
            continue
        try:
            presenti.append(assicura(voce["name"].strip(), ruolo=str(voce.get("role") or ""),
                                     agate_agent_id=str(voce.get("agate_agent_id") or ""), azienda=azienda))
        except AgenteSconosciuto as e:
            log.warning("agente %s non creato: %s", voce["name"][:100], e)
    Agente.objects.filter(tecnico=False, attivo=True).exclude(pk__in=[a.pk for a in presenti]).update(attivo=False)
    return presenti


def riallinea_tutti(azienda):
    """Dopo un cambio dell'azienda degli agenti: tutti i profili agente puntano alla nuova."""
    for agente in Agente.objects.select_related("utente"):
        confina(agente, azienda)


# ---------- niente interfaccia per gli agenti ----------

def accesso_negato(sender, request, user, **kwargs):
    """Ricevitore di `user_logged_in`: un utente agente che entra (con qualunque backend) esce subito con 403."""
    if not e_agente(user):
        return
    if request is not None:
        if hasattr(request, "session"):
            request.session.flush()
        request.user = AnonymousUser()
    log.warning("accesso all'interfaccia negato all'utente agente %s", user.username)
    raise PermissionDenied("Gli utenti agente non usano l'interfaccia.")


def token_negato(sender, instance, raw=False, **kwargs):
    """Ricevitore di `pre_save` di `TokenApi`: un utente agente non ha token API."""
    if not raw and e_agente(instance.utente):
        raise PermissionDenied("Gli utenti agente non hanno token API.")
