"""Quali chat possono collegarsi, e come si presentano: con un documento pubblico al loro indirizzo (CIMD), con la
registrazione che fanno da sé (DCR), o con le credenziali che un amministratore crea a mano (Gemini Enterprise).

La protezione sta negli indirizzi di ritorno: il codice che dà accesso ai dati parte solo verso quelli di un fornitore
noto, o aggiunti a mano nelle impostazioni. Chiunque può presentarsi come client, ma con un ritorno fuori elenco non
ottiene nulla."""
import json
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.utils import timezone

from core import parametri, rete

from .models import ClientOAuth

# Indirizzi di ritorno dei fornitori, dalla loro documentazione letta il 2026-11-12. `ritorni`: uguaglianza esatta;
# `prefissi`: l'indirizzo comincia così e prosegue con un identificativo messo dal fornitore.
# Da fonti non ufficiali, da confermare alla prima prova vera: i prefissi `googleusercontent` dell'app Gemini (che fuori
# dagli Stati Uniti non ha ancora le app personalizzate) e il ritorno di Le Chat.
FORNITORI = {
    "claude": {"ritorni": ["https://claude.ai/api/mcp/auth_callback"], "prefissi": []},
    "chatgpt": {"ritorni": ["https://chatgpt.com/connector_platform_oauth_redirect"],
                "prefissi": ["https://chatgpt.com/connector/oauth/"]},
    "gemini": {"ritorni": ["https://vertexaisearch.cloud.google.com/oauth-redirect",       # Gemini Enterprise
                           "https://antigravity.google/oauth-callback"],                  # Antigravity
               "prefissi": [f"https://oauth-redirect{variante}.googleusercontent.com/{percorso}/user_bound_custom-mcp-"
                            for variante in ("", "-sandbox", "-test") for percorso in ("r", "a")]},
    "mistral": {"ritorni": ["https://callback.mistral.ai/v1/integrations_auth/oauth2_callback"], "prefissi": []},
}
# i fornitori che vogliono un client creato a mano, con il loro unico indirizzo di ritorno
A_MANO = {"gemini": ("Gemini Enterprise", "https://vertexaisearch.cloud.google.com/oauth-redirect")}
VALIDITA_DOCUMENTO = timedelta(hours=24)
MAX_DOCUMENTO = 100_000
MAX_RITORNI = 12
METODI_TOKEN = ("none", "client_secret_post", "client_secret_basic")
REGISTRAZIONI_ORA = 60


class ClientNonValido(Exception):
    """Il client o il suo indirizzo di ritorno non sono accettabili: l'errore si mostra, non si rimanda al client."""

    def __init__(self, descrizione, codice="invalid_client"):
        super().__init__(descrizione)
        self.codice, self.descrizione = codice, descrizione


def _impostazione(chiave):
    try:
        return parametri.leggi(f"connettore_ai.{chiave}")
    except KeyError:
        return None


def _locale(parti):
    return parti.scheme == "http" and parti.hostname in ("127.0.0.1", "localhost", "::1")


def fornitore_di(uri):
    """Il fornitore a cui appartiene un indirizzo di ritorno, "locale" per i programmi sul computer dell'utente, "altro"
    per quelli aggiunti a mano, "" se l'indirizzo non è ammesso."""
    try:
        parti = urlsplit(uri)
    except ValueError:
        return ""
    if parti.fragment or parti.username or parti.password:
        return ""
    if _locale(parti):
        return "locale" if _impostazione("client_locali") else ""
    if parti.scheme != "https":
        return ""
    for nome, f in FORNITORI.items():
        if uri in f["ritorni"] or any(uri.startswith(p) and len(uri) > len(p) for p in f["prefissi"]):
            return nome
    for voce in str(_impostazione("ritorni_extra") or "").split():
        if voce.startswith("https://") and (uri == voce or (voce.endswith("*") and uri.startswith(voce[:-1]))):
            return "altro"
    return ""


def origine_valida(origine):
    """L'intestazione Origin, quando c'è, deve essere un'origine web ben formata. Non c'è un elenco di origini ammesse:
    nessun fornitore dichiara la sua, e un controllo stretto respingerebbe chiamate buone. Il DNS rebinding, che è il
    motivo del controllo nello standard, qui lo ferma già ALLOWED_HOSTS; e il token non è un cookie che il browser
    allega da solo."""
    try:
        parti = urlsplit(origine)
    except ValueError:
        return False
    return bool(parti.hostname) and not parti.path.strip("/") and not parti.query and (parti.scheme == "https" or _locale(parti))


def ritorno_del_client(client, uri):
    """True se `uri` è tra gli indirizzi dichiarati dal client. Per i programmi locali la porta può cambiare a ogni
    accesso (RFC 8252): si confronta tutto il resto."""
    if uri in client.redirect_uris:
        return True
    parti = urlsplit(uri)
    if not _locale(parti):
        return False
    return any(_locale(d := urlsplit(dichiarato)) and (d.hostname, d.path, d.query) == (parti.hostname, parti.path, parti.query)
               for dichiarato in client.redirect_uris)


def _ritorni_validi(ritorni):
    """(indirizzi, fornitore) se tutti gli indirizzi dichiarati sono ammessi."""
    if not isinstance(ritorni, list) or not ritorni or len(ritorni) > MAX_RITORNI \
            or not all(isinstance(r, str) and len(r) <= 600 for r in ritorni):
        raise ClientNonValido("redirect_uris: serve un elenco di indirizzi", "invalid_redirect_uri")
    fornitori = {fornitore_di(r) for r in ritorni}
    if "" in fornitori:
        raise ClientNonValido("redirect_uris: indirizzo di ritorno non ammesso da questa istanza", "invalid_redirect_uri")
    return ritorni, (fornitori.pop() if len(fornitori) == 1 else "altro")


def _nome(dati):
    return dati["client_name"][:120] if isinstance(dati.get("client_name"), str) else ""


# ---------- CIMD: il client è un documento pubblico ----------

def _scarica_documento(url):
    """Il documento JSON del client. Niente reindirizzamenti, solo https verso indirizzi pubblici (core.rete)."""
    try:
        testo, _ = rete.scarica(url, tipi=("application/json",), massimo=MAX_DOCUMENTO, reindirizzamenti=0)
    except rete.Rifiutato as e:
        raise ClientNonValido(f"documento del client non leggibile: {e}") from e
    except Exception as e:                              # rete: tempo scaduto, connessione rifiutata…
        raise ClientNonValido("documento del client non raggiungibile") from e
    if len(testo.encode()) > MAX_DOCUMENTO:
        raise ClientNonValido("documento del client troppo grande")
    try:
        return json.loads(testo)
    except ValueError as e:
        raise ClientNonValido("il documento del client non è JSON") from e


def _da_documento(client_id):
    parti = urlsplit(client_id)
    if parti.scheme != "https" or not parti.hostname or parti.path in ("", "/") or parti.fragment or parti.username or parti.password:
        raise ClientNonValido("client_id: serve un indirizzo https con un percorso")
    dati = _scarica_documento(client_id)
    if not isinstance(dati, dict) or dati.get("client_id") != client_id:
        raise ClientNonValido("il documento non dichiara lo stesso client_id del suo indirizzo")
    ritorni, fornitore = _ritorni_validi(dati.get("redirect_uris"))
    # un documento pubblico non ha un segreto: il client deve poter fare da client pubblico (ChatGPT dichiara
    # private_key_jwt ma accetta anche «none», e sceglie tra i metodi che offriamo noi)
    offerti = dati.get("token_endpoint_auth_methods_supported")
    if dati.get("token_endpoint_auth_method", "none") != "none" and not (isinstance(offerti, list) and "none" in offerti):
        raise ClientNonValido("il documento chiede un'autenticazione al token che questa istanza non offre")
    client, _ = ClientOAuth.objects.update_or_create(client_id=client_id, defaults={
        "tipo": ClientOAuth.CIMD, "nome": _nome(dati), "fornitore": fornitore, "redirect_uris": ritorni,
        "autenticazione": "none", "letto": timezone.now()})
    return client


def trova(client_id, rileggi=True):
    """Il client con quell'identificativo; un indirizzo https è un documento da leggere (al più una volta al giorno).
    Senza `rileggi` vale quello già letto: allo scambio del codice la rete non deve far aspettare."""
    client_id = str(client_id or "")
    if not client_id or len(client_id) > 500:
        raise ClientNonValido("client_id mancante o non valido")
    client = ClientOAuth.objects.filter(client_id=client_id).first()
    if client_id.startswith("https://"):
        letto = client is not None and client.tipo == ClientOAuth.CIMD and client.letto is not None
        if letto and (not rileggi or timezone.now() - client.letto <= VALIDITA_DOCUMENTO):
            return client
        if not rileggi:
            raise ClientNonValido("client sconosciuto")
        return _da_documento(client_id)
    if client is None or client.tipo == ClientOAuth.CIMD:
        raise ClientNonValido("client sconosciuto: va registrato di nuovo")
    return client


# ---------- DCR e client creati a mano ----------

def _crea(tipo, nome, fornitore, ritorni, metodo):
    """(client, segreto in chiaro o ""). Del segreto resta solo l'impronta."""
    from .oauth import impronta
    segreto = "" if metodo == "none" else "cai_s_" + secrets.token_urlsafe(32)
    client = ClientOAuth.objects.create(
        client_id="cai_c_" + secrets.token_urlsafe(18), tipo=tipo, nome=nome, fornitore=fornitore, redirect_uris=ritorni,
        autenticazione=metodo, impronta=impronta(segreto) if segreto else "")
    return client, segreto


def registra(dati):
    """(client, segreto in chiaro o "") da una richiesta di registrazione (RFC 7591)."""
    if not isinstance(dati, dict):
        raise ClientNonValido("corpo della registrazione non valido", "invalid_client_metadata")
    ritorni, fornitore = _ritorni_validi(dati.get("redirect_uris"))
    metodo = dati.get("token_endpoint_auth_method", "none")
    if metodo not in METODI_TOKEN:
        raise ClientNonValido("token_endpoint_auth_method non offerto", "invalid_client_metadata")
    risposte, concessioni = dati.get("response_types", ["code"]), dati.get("grant_types", ["authorization_code"])
    if risposte != ["code"] or not isinstance(concessioni, list) or not set(concessioni) <= {"authorization_code", "refresh_token"}:
        raise ClientNonValido("si offre solo il flusso con codice di autorizzazione", "invalid_client_metadata")
    un_ora_fa = timezone.now() - timedelta(hours=1)
    if ClientOAuth.objects.filter(tipo=ClientOAuth.DCR, creato__gte=un_ora_fa).count() >= REGISTRAZIONI_ORA:
        raise ClientNonValido("troppe registrazioni: riprova più tardi", "temporarily_unavailable")
    return _crea(ClientOAuth.DCR, _nome(dati), fornitore, ritorni, metodo)


def crea_a_mano(fornitore):
    """(client, segreto) per un fornitore che vuole credenziali inserite da un amministratore nella sua console."""
    nome, ritorno = A_MANO[fornitore]
    return _crea(ClientOAuth.A_MANO, nome, fornitore, [ritorno], "client_secret_basic")
