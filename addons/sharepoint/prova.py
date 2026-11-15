"""La SharePoint finta: risponde nel formato di Microsoft Graph (token «client credentials», sito, raccolte, driveItem
con cTag, figli a pagine con @odata.nextLink, download con rimando, caricamento semplice e a sessione) senza uscire in
rete. Capisce solo le chiamate che fa il connettore. File e cartelle stanno in FileProva, per percorso dalla radice."""
import json
import secrets
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

import httpx2 as httpx

from .graph import GRAPH, LOGIN
from .models import FileProva

TENANT = "prova.onmicrosoft.com"
SITO = "prova.sharepoint.com/sites/Adabox"
TOKEN = "prova-graph"
DRIVE = "b!prova-documenti"
LIBRERIA = "Documenti condivisi"
SITO_ID = "prova.sharepoint.com,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222"
FILE_HOST = "https://prova.sharepoint.com"
PER_PAGINA = 3                          # pagine piccole: così il connettore segue davvero @odata.nextLink
_sessioni = {}                          # caricamenti a sessione in corso: token → {collegamento, percorso, dati}


def nuovo_ctag():
    return f'"c:{{{uuid.uuid4()}}},1"'


def _errore(stato, codice, messaggio):
    return httpx.Response(stato, json={"error": {"code": codice, "message": messaggio}})


def _padre(percorso):
    return percorso.rpartition("/")[0]


def _voce(f):
    voce = {"id": f.id_esterno, "name": f.percorso.rpartition("/")[2], "eTag": f.ctag, "lastModifiedDateTime": f.modificato.isoformat()}
    if f.cartella:
        voce["folder"] = {"childCount": 0}
    else:
        voce.update({"cTag": f.ctag, "size": len(bytes(f.contenuto)), "file": {"mimeType": "application/octet-stream"}})
    return voce


def _per_id(collegamento, item_id):
    """(percorso, FileProva o None per la radice) dell'item."""
    if item_id == "root":
        return "", None
    f = FileProva.objects.filter(collegamento=collegamento, id_esterno=item_id).first()
    return (f.percorso, f) if f else (None, None)


def _assicura_cartelle(collegamento, percorso):
    """Le cartelle che portano a `percorso` (come fa SharePoint quando si carica in un percorso nuovo)."""
    parti = percorso.split("/") if percorso else []
    for i in range(1, len(parti) + 1):
        FileProva.objects.get_or_create(collegamento=collegamento, percorso="/".join(parti[:i]),
                                        defaults={"cartella": True, "id_esterno": "F" + secrets.token_hex(8), "ctag": nuovo_ctag()})


def scrivi(collegamento, percorso, contenuto):
    """Un file sulla SharePoint finta (nuovo o sostituito), con un cTag nuovo."""
    _assicura_cartelle(collegamento, _padre(percorso))
    f, _ = FileProva.objects.get_or_create(collegamento=collegamento, percorso=percorso,
                                           defaults={"id_esterno": "I" + secrets.token_hex(8)})
    f.contenuto, f.ctag, f.cartella = contenuto, nuovo_ctag(), False
    f.save()
    return f


def prepara(collegamento):
    """Alla prima prova la cartella collegata c'è già, con un file di benvenuto."""
    if FileProva.objects.filter(collegamento=collegamento).exists():
        return
    base = collegamento.percorso.strip("/")
    _assicura_cartelle(collegamento, base)
    scrivi(collegamento, f"{base}/Benvenuto.txt" if base else "Benvenuto.txt",
           "Questo file sta sulla SharePoint finta del collegamento in prova.".encode())


def trasporto(collegamento):
    """Il trasporto httpx che fa le veci di Microsoft Graph per questo collegamento."""

    def risposta(richiesta):
        url = str(richiesta.url)
        if url.startswith(LOGIN + "/"):
            return _token(richiesta)
        if url.startswith(FILE_HOST + "/"):
            return _file_host(collegamento, richiesta)
        if not url.startswith(GRAPH + "/"):
            return _errore(400, "invalidRequest", "Indirizzo non di Graph")
        if richiesta.headers.get("Authorization") != f"Bearer {TOKEN}":
            return _errore(401, "InvalidAuthenticationToken", "Access token is empty or invalid.")
        return _graph(collegamento, richiesta, unquote(urlsplit(url).path[len("/v1.0"):]), parse_qs(urlsplit(url).query))

    return httpx.MockTransport(risposta)


def _token(richiesta):
    dati = parse_qs(richiesta.content.decode())
    if dati.get("grant_type") != ["client_credentials"] or dati.get("scope") != ["https://graph.microsoft.com/.default"]:
        return httpx.Response(400, json={"error": "invalid_request", "error_description": "AADSTS900144: missing parameter"})
    return httpx.Response(200, json={"token_type": "Bearer", "expires_in": 3599, "access_token": TOKEN})


def _graph(c, richiesta, percorso, query):
    metodo = richiesta.method
    if percorso.startswith("/sites/"):
        if percorso == "/sites/prova.sharepoint.com:/sites/Adabox" or percorso == f"/sites/{SITO_ID}":
            return httpx.Response(200, json={"id": SITO_ID, "displayName": "Adabox (prova)", "webUrl": f"https://{SITO}"})
        if percorso == f"/sites/{SITO_ID}/drive":
            return httpx.Response(200, json={"id": DRIVE, "name": LIBRERIA})
        if percorso == f"/sites/{SITO_ID}/drives":
            return httpx.Response(200, json={"value": [{"id": DRIVE, "name": LIBRERIA, "driveType": "documentLibrary"}]})
        return _errore(404, "itemNotFound", "Requested site could not be found")
    radice = f"/drives/{DRIVE}"
    if not percorso.startswith(radice):
        return _errore(404, "itemNotFound", "Drive not found")
    resto = percorso[len(radice):]
    if resto == "/root" and metodo == "GET":
        return httpx.Response(200, json={"id": "root", "name": "root", "folder": {}})
    if resto.startswith("/root:/") and metodo == "GET":
        f = FileProva.objects.filter(collegamento=c, percorso=resto[len("/root:/"):].strip("/")).first()
        return httpx.Response(200, json=_voce(f)) if f else _errore(404, "itemNotFound", "The resource could not be found.")
    if not resto.startswith("/items/"):
        return _errore(400, "invalidRequest", "Chiamata non gestita dalla prova")
    dopo = resto[len("/items/"):]
    if ":/" in dopo:                                    # /items/{padre}:/{nome}:[/content|/createUploadSession]
        item_id, _, sotto = dopo.partition(":/")
        nome, _, azione = sotto.partition(":")
        return _per_nome(c, richiesta, item_id, nome, azione)
    item_id, _, coda = dopo.partition("/")
    base, f = _per_id(c, item_id)
    if base is None:
        return _errore(404, "itemNotFound", "The resource could not be found.")
    if coda == "children" and metodo == "GET":
        figli = [x for x in FileProva.objects.filter(collegamento=c).order_by("percorso")
                 if _padre(x.percorso) == base and x.percorso != base]
        inizio = int(query.get("$skiptoken", ["0"])[0])
        dati = {"value": [_voce(x) for x in figli[inizio:inizio + PER_PAGINA]]}
        if inizio + PER_PAGINA < len(figli):
            dati["@odata.nextLink"] = f"{GRAPH}/drives/{DRIVE}/items/{item_id}/children?$skiptoken={inizio + PER_PAGINA}"
        return httpx.Response(200, json=dati)
    if coda == "children" and metodo == "POST":
        corpo = json.loads(richiesta.content)
        nuovo = f"{base}/{corpo['name']}" if base else corpo["name"]
        if FileProva.objects.filter(collegamento=c, percorso=nuovo).exists():
            return _errore(409, "nameAlreadyExists", "An item with the same name already exists.")
        _assicura_cartelle(c, nuovo)
        return httpx.Response(201, json=_voce(FileProva.objects.get(collegamento=c, percorso=nuovo)))
    if coda == "content" and metodo == "GET" and f is not None and not f.cartella:
        return httpx.Response(302, headers={"Location": f"{FILE_HOST}/download/{f.id_esterno}?tempauth={secrets.token_hex(6)}"})
    if coda == "" and metodo == "PATCH" and f is not None:
        corpo = json.loads(richiesta.content)
        nuova_base, _ = _per_id(c, corpo["parentReference"]["id"])
        if nuova_base is None:
            return _errore(400, "invalidRequest", "Parent not found")
        nuovo = f"{nuova_base}/{corpo['name']}" if nuova_base else corpo["name"]
        FileProva.objects.filter(collegamento=c, percorso=nuovo).exclude(pk=f.pk).delete()      # conflictBehavior replace
        f.percorso = nuovo
        f.save()
        return httpx.Response(200, json=_voce(f))
    return _errore(400, "invalidRequest", "Chiamata non gestita dalla prova")


def _per_nome(c, richiesta, padre_id, nome, azione):
    base, padre = _per_id(c, padre_id)
    if base is None or (padre is not None and not padre.cartella):
        return _errore(404, "itemNotFound", "The resource could not be found.")
    percorso = f"{base}/{nome}" if base else nome
    if azione == "" and richiesta.method == "GET":
        f = FileProva.objects.filter(collegamento=c, percorso=percorso).first()
        return httpx.Response(200, json=_voce(f)) if f else _errore(404, "itemNotFound", "The resource could not be found.")
    if azione == "/content" and richiesta.method == "PUT":
        esisteva = FileProva.objects.filter(collegamento=c, percorso=percorso).exists()
        return httpx.Response(200 if esisteva else 201, json=_voce(scrivi(c, percorso, richiesta.content)))
    if azione == "/createUploadSession" and richiesta.method == "POST":
        token = secrets.token_hex(8)
        _sessioni[token] = {"collegamento": c.pk, "percorso": percorso, "dati": bytearray()}
        return httpx.Response(200, json={"uploadUrl": f"{FILE_HOST}/upload/{token}", "expirationDateTime": "2099-01-01T00:00:00Z"})
    return _errore(400, "invalidRequest", "Chiamata non gestita dalla prova")


def _file_host(c, richiesta):
    """Gli indirizzi pre-autenticati: non vogliono il token di Graph."""
    if "Authorization" in richiesta.headers:
        return _errore(400, "invalidRequest", "Gli indirizzi pre-autenticati non accettano Authorization")
    percorso = urlsplit(str(richiesta.url)).path
    if percorso.startswith("/download/") and richiesta.method == "GET":
        f = FileProva.objects.filter(collegamento=c, id_esterno=percorso[len("/download/"):], cartella=False).first()
        return httpx.Response(200, content=bytes(f.contenuto)) if f else _errore(404, "itemNotFound", "Not found")
    if percorso.startswith("/upload/") and richiesta.method == "PUT":
        sessione = _sessioni.get(percorso[len("/upload/"):])
        if sessione is None or sessione["collegamento"] != c.pk:
            return _errore(404, "itemNotFound", "Upload session not found")
        intervallo, _, totale = richiesta.headers["Content-Range"].removeprefix("bytes ").partition("/")
        inizio = int(intervallo.split("-")[0])
        if inizio != len(sessione["dati"]):
            return _errore(416, "invalidRange", "Fragment out of order")
        sessione["dati"] += richiesta.content
        if len(sessione["dati"]) < int(totale):
            return httpx.Response(202, json={"nextExpectedRanges": [f"{len(sessione['dati'])}-"]})
        _sessioni.pop(percorso[len("/upload/"):])
        esisteva = FileProva.objects.filter(collegamento=c, percorso=sessione["percorso"]).exists()
        return httpx.Response(200 if esisteva else 201, json=_voce(scrivi(c, sessione["percorso"], bytes(sessione["dati"]))))
    return _errore(400, "invalidRequest", "Chiamata non gestita dalla prova")
