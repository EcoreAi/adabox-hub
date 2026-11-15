"""SharePoint attraverso Microsoft Graph, con il flusso OAuth «client credentials» di un'app registrata in Microsoft
Entra ID (ex Azure AD).

Documentazione: learn.microsoft.com/graph, risorse site, drive e driveItem. Il token si chiede a
https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token con scope https://graph.microsoft.com/.default e non ha
refresh token: scaduto, se ne chiede un altro. All'app servono i permessi applicativi Sites.Selected (con l'accesso in
scrittura concesso al solo sito) oppure Sites.ReadWrite.All. Le chiamate vanno solo a graph.microsoft.com e
login.microsoftonline.com; i file si scaricano e si caricano oltre i 4 MB da indirizzi pre-autenticati che Graph
restituisce, ammessi solo se sono https su un dominio di Microsoft (sharepoint.com, svc.ms)."""
import datetime
import re
from urllib.parse import quote, urlsplit

import httpx2 as httpx

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
SCOPE = "https://graph.microsoft.com/.default"
TEMPO = 30
PICCOLO = 4 * 1024 * 1024               # fino a 4 MB un file si carica con una chiamata, oltre con una sessione
PEZZO = 320 * 1024 * 16                 # 5 MiB: i pezzi di una sessione devono essere multipli di 320 KiB
CAMPI = "id,name,size,eTag,cTag,file,folder,lastModifiedDateTime"
PER_PAGINA = 200
MAX_VOCI = 5000                         # oltre, la cartella si legge solo in parte (e non si cestina nulla)
HOST_FILE = (".sharepoint.com", ".svc.ms")
TENANT = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[a-z0-9-]+(\.[a-z0-9-]+)+)$", re.I)
VIETATI = re.compile(r'["*:<>?/\\|\x00-\x1f]')     # caratteri che SharePoint non ammette nei nomi
MARGINE_TOKEN = datetime.timedelta(minutes=5)


class ErroreSharePoint(RuntimeError):
    """Serve una persona: credenziali sbagliate, sito o cartella che non ci sono, permessi mancanti."""


class ErroreTemporaneo(ErroreSharePoint):
    """Rete, troppe richieste, server in difficoltà: si riprova più tardi."""


# --- valori scritti dall'utente -------------------------------------------------------------------------------------

def tenant_valido(valore):
    """L'id della directory (GUID) o un suo dominio (azienda.onmicrosoft.com)."""
    valore = (valore or "").strip().lower()
    if not TENANT.match(valore):
        raise ErroreSharePoint("Indica l'ID della directory (tenant) o il dominio, es. «azienda.onmicrosoft.com».")
    return valore


def sito_valido(valore):
    """«https://azienda.sharepoint.com/sites/Ufficio» → «azienda.sharepoint.com/sites/Ufficio» (senza la pagina)."""
    valore = (valore or "").strip()
    parti = urlsplit(valore if "://" in valore else f"https://{valore}")
    host = (parti.hostname or "").lower()
    if not host.endswith(".sharepoint.com") or host.count(".") < 2:
        raise ErroreSharePoint("Indica l'indirizzo del sito, es. «https://azienda.sharepoint.com/sites/Ufficio».")
    pezzi = [p for p in parti.path.split("/") if p]
    if len(pezzi) >= 2 and pezzi[0].lower() in ("sites", "teams"):
        return f"{host}/{pezzi[0].lower()}/{pezzi[1]}"
    return host                                          # il sito principale


def percorso_pulito(valore):
    """«/Progetti/Offerte/» → «Progetti/Offerte»; niente «.» o «..»."""
    pezzi = [p.strip() for p in (valore or "").replace("\\", "/").split("/") if p.strip()]
    if any(p in (".", "..") or VIETATI.search(p) for p in pezzi):
        raise ErroreSharePoint("Il percorso della cartella contiene caratteri non ammessi.")
    return "/".join(pezzi)


def nome_per_sharepoint(nome):
    """Il nome di un file o di una cartella come lo accetta SharePoint: i caratteri vietati diventano «_»."""
    nome = VIETATI.sub("_", nome or "").strip().rstrip(".").strip()
    return nome[:250] or "senza nome"


def _indirizzo_file(url):
    """Gli indirizzi pre-autenticati di download e upload: solo https su un dominio di Microsoft."""
    parti = urlsplit(url or "")
    host = (parti.hostname or "").lower()
    if parti.scheme != "https" or parti.username or parti.password or not host.endswith(HOST_FILE):
        raise ErroreSharePoint("Microsoft Graph ha risposto con un indirizzo inatteso per il file.")
    return url


def _graph(url):
    """Le pagine successive (@odata.nextLink) restano su Graph."""
    if not (url or "").startswith(GRAPH + "/"):
        raise ErroreSharePoint("Microsoft Graph ha risposto con un indirizzo di pagina inatteso.")
    return url


def _p(testo):
    return quote(testo, safe="")


def _percorso_url(percorso):
    return "/".join(_p(p) for p in percorso.split("/"))


class Deposito:
    """Dove tenere il token tra un lavoro e l'altro (cifrato sul collegamento); senza, vive quanto il client."""

    def leggi(self):
        return None

    def salva(self, token, scade):
        pass


class Graph:
    def __init__(self, tenant, client_id, segreto, deposito=None, transport=None):
        self.tenant, self.client_id, self.segreto = tenant, client_id, segreto
        self.deposito = deposito or Deposito()
        self.http = httpx.Client(timeout=TEMPO, transport=transport, trust_env=False, follow_redirects=False)
        self._accesso = None

    def chiudi(self):
        self.http.close()

    # --- accesso -----------------------------------------------------------------------------------------------------

    def _token(self, nuovo=False):
        if self._accesso is None and not nuovo:
            self._accesso = self.deposito.leggi()
        if self._accesso and not nuovo:
            return self._accesso
        try:
            r = self.http.post(f"{LOGIN}/{_p(self.tenant)}/oauth2/v2.0/token", data={
                "grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.segreto, "scope": SCOPE})
        except httpx.HTTPError as e:
            raise ErroreTemporaneo(f"Microsoft Entra non risponde: {e.__class__.__name__}.") from e
        if r.status_code >= 500 or r.status_code == 429:
            raise ErroreTemporaneo(f"Microsoft Entra risponde {r.status_code}: si riprova più tardi.")
        try:
            dati = r.json()
        except ValueError:
            dati = {}
        if r.status_code != 200 or not dati.get("access_token"):
            codice = str(dati.get("error_description") or dati.get("error") or r.status_code).splitlines()[0][:200]
            raise ErroreSharePoint(f"Accesso a Microsoft rifiutato: controlla tenant, client id e client secret ({codice}).")
        durata = datetime.timedelta(seconds=int(dati.get("expires_in") or 3600))
        self._accesso = dati["access_token"]
        self.deposito.salva(self._accesso, datetime.datetime.now(datetime.timezone.utc) + durata - MARGINE_TOKEN)
        return self._accesso

    # --- chiamate ----------------------------------------------------------------------------------------------------

    def _chiama(self, metodo, url, attesi=(200,), **kwargs):
        url = url if url.startswith("https://") else GRAPH + url
        intestazioni = kwargs.pop("headers", {})
        for tentativo in (1, 2):                          # al 401 si chiede un token nuovo, una volta
            token = self._token(nuovo=tentativo == 2)
            try:
                r = self.http.request(metodo, url, headers={**intestazioni, "Authorization": f"Bearer {token}"}, **kwargs)
            except httpx.HTTPError as e:
                raise ErroreTemporaneo(f"SharePoint non risponde: {e.__class__.__name__}.") from e
            if r.status_code != 401:
                break
        if r.status_code in attesi:
            return r
        self._errore(r)

    @staticmethod
    def _errore(r):
        try:
            errore = r.json().get("error") or {}
        except ValueError:
            errore = {}
        messaggio = str(errore.get("message") or "").splitlines()[0][:200] if isinstance(errore, dict) else ""
        if r.status_code == 429 or r.status_code >= 500:
            attesa = r.headers.get("Retry-After")
            raise ErroreTemporaneo(f"SharePoint risponde {r.status_code}" + (f", riprovare tra {attesa} s" if attesa else "") + ".")
        if r.status_code == 401:
            raise ErroreSharePoint("Microsoft ha rifiutato il token: controlla le credenziali dell'app.")
        if r.status_code == 403:
            raise ErroreSharePoint("L'app non ha accesso al sito: concedile Sites.Selected in scrittura sul sito (o Sites.ReadWrite.All).")
        if r.status_code == 404:
            raise NonTrovato(messaggio or "Non trovato.")
        raise ErroreSharePoint(f"SharePoint ha rifiutato la richiesta ({r.status_code}){': ' + messaggio if messaggio else ''}.")

    def _json(self, metodo, url, attesi=(200,), **kwargs):
        r = self._chiama(metodo, url, attesi=attesi, **kwargs)
        try:
            return r.json()
        except ValueError as e:
            raise ErroreTemporaneo("SharePoint ha risposto con dati illeggibili.") from e

    # --- sito, libreria, cartella ------------------------------------------------------------------------------------

    def sito(self, sito):
        """{id, nome, url} del sito «host» o «host/sites/Nome»."""
        host, _, percorso = sito.partition("/")
        url = f"/sites/{_p(host)}" + (f":/{_percorso_url(percorso)}" if percorso else "")
        try:
            dati = self._json("GET", url, params={"$select": "id,displayName,webUrl"})
        except NonTrovato as e:
            raise ErroreSharePoint(f"Il sito «{sito}» non esiste o l'app non lo vede.") from e
        return {"id": dati["id"], "nome": dati.get("displayName") or sito, "url": dati.get("webUrl") or ""}

    def libreria(self, sito_id, nome=""):
        """L'id della raccolta documenti chiamata `nome` (senza nome: quella predefinita del sito)."""
        if not nome:
            return self._json("GET", f"/sites/{_p(sito_id)}/drive", params={"$select": "id,name"})["id"]
        dati = self._json("GET", f"/sites/{_p(sito_id)}/drives", params={"$select": "id,name,driveType"})
        for d in dati.get("value", []):
            if (d.get("name") or "").strip().lower() == nome.strip().lower():
                return d["id"]
        nomi = ", ".join(f"«{d.get('name')}»" for d in dati.get("value", [])) or "nessuna"
        raise ErroreSharePoint(f"Nel sito non c'è la raccolta documenti «{nome}» (ci sono: {nomi}).")

    def cartella(self, drive_id, percorso, crea=False):
        """L'id della cartella al `percorso` nella libreria («» = la radice); con `crea` si crea se manca."""
        if not percorso:
            return self._json("GET", f"/drives/{_p(drive_id)}/root", params={"$select": "id"})["id"]
        try:
            dati = self._json("GET", f"/drives/{_p(drive_id)}/root:/{_percorso_url(percorso)}", params={"$select": "id,folder"})
        except NonTrovato:
            if not crea:
                raise ErroreSharePoint(f"Nella libreria non c'è la cartella «{percorso}».") from None
            padre = self.cartella(drive_id, "", crea=False)
            for nome in percorso.split("/"):
                padre = self.sottocartella(drive_id, padre, nome)
            return padre
        if "folder" not in dati:
            raise ErroreSharePoint(f"«{percorso}» nella libreria è un file, non una cartella.")
        return dati["id"]

    def sottocartella(self, drive_id, padre_id, nome):
        """L'id della cartella `nome` dentro `padre_id`, creata se manca."""
        nome = nome_per_sharepoint(nome)
        try:
            return self._json("GET", f"/drives/{_p(drive_id)}/items/{_p(padre_id)}:/{_p(nome)}:", params={"$select": "id"})["id"]
        except NonTrovato:
            pass
        r = self._chiama("POST", f"/drives/{_p(drive_id)}/items/{_p(padre_id)}/children", attesi=(200, 201, 409),
                         json={"name": nome, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
        if r.status_code == 409:                         # creata nel frattempo
            return self._json("GET", f"/drives/{_p(drive_id)}/items/{_p(padre_id)}:/{_p(nome)}:", params={"$select": "id"})["id"]
        return r.json()["id"]

    # --- lettura -----------------------------------------------------------------------------------------------------

    def figli(self, drive_id, item_id):
        url, params = f"/drives/{_p(drive_id)}/items/{_p(item_id)}/children", {"$select": CAMPI, "$top": PER_PAGINA}
        while url:
            dati = self._json("GET", url, params=params)
            yield from dati.get("value", [])
            url, params = dati.get("@odata.nextLink"), None
            if url:
                _graph(url)

    def albero(self, drive_id, item_id, massimo=MAX_VOCI):
        """(voci, completo): le voci sotto la cartella, ognuna {percorso relativo, cartella (bool), item}."""
        voci, coda = [], [("", item_id)]
        while coda:
            base, cartella_id = coda.pop(0)
            for item in self.figli(drive_id, cartella_id):
                if len(voci) >= massimo:
                    return voci, False
                percorso = f"{base}/{item['name']}" if base else item["name"]
                if "folder" in item:
                    voci.append({"percorso": percorso, "cartella": True, "item": item})
                    coda.append((percorso, item["id"]))
                elif "file" in item:
                    voci.append({"percorso": percorso, "cartella": False, "item": item})
        return voci, True

    def scarica(self, drive_id, item_id, massimo):
        """I byte del file (al massimo `massimo`): Graph rimanda a un indirizzo pre-autenticato, senza il nostro token."""
        r = self._chiama("GET", f"/drives/{_p(drive_id)}/items/{_p(item_id)}/content", attesi=(200, 302))
        if r.status_code == 200:
            if len(r.content) > massimo:
                raise ErroreSharePoint("file troppo grande")
            return r.content
        url = _indirizzo_file(r.headers.get("Location"))
        dati = bytearray()
        try:
            with self.http.stream("GET", url) as risposta:
                if risposta.status_code != 200:
                    risposta.read()
                    self._errore(risposta)
                for pezzo in risposta.iter_bytes():
                    dati += pezzo
                    if len(dati) > massimo:
                        raise ErroreSharePoint("file troppo grande")
        except httpx.HTTPError as e:
            raise ErroreTemporaneo(f"Download da SharePoint interrotto: {e.__class__.__name__}.") from e
        return bytes(dati)

    # --- scrittura ---------------------------------------------------------------------------------------------------

    def carica(self, drive_id, padre_id, nome, contenuto):
        """Scrive il file `nome` in `padre_id` (sostituisce quello che c'è) e ne restituisce l'item."""
        nome = nome_per_sharepoint(nome)
        indirizzo = f"/drives/{_p(drive_id)}/items/{_p(padre_id)}:/{_p(nome)}:"
        if len(contenuto) <= PICCOLO:
            return self._json("PUT", indirizzo + "/content", attesi=(200, 201), content=contenuto,
                              headers={"Content-Type": "application/octet-stream"})
        sessione = self._json("POST", indirizzo + "/createUploadSession", json={"item": {"@microsoft.graph.conflictBehavior": "replace"}})
        url, totale = _indirizzo_file(sessione.get("uploadUrl")), len(contenuto)
        for inizio in range(0, totale, PEZZO):
            pezzo = contenuto[inizio:inizio + PEZZO]
            fine = inizio + len(pezzo) - 1
            try:                                          # l'indirizzo della sessione è già autorizzato: niente token
                r = self.http.put(url, content=pezzo, headers={"Content-Range": f"bytes {inizio}-{fine}/{totale}",
                                                                "Content-Length": str(len(pezzo))})
            except httpx.HTTPError as e:
                raise ErroreTemporaneo(f"Caricamento su SharePoint interrotto: {e.__class__.__name__}.") from e
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code != 202:
                self._errore(r)
        raise ErroreTemporaneo("SharePoint non ha chiuso il caricamento.")

    def sposta(self, drive_id, item_id, padre_id, nome):
        """Rinomina e/o sposta un file già su SharePoint (così un documento rinominato non lascia un doppione)."""
        return self._json("PATCH", f"/drives/{_p(drive_id)}/items/{_p(item_id)}", json={
            "name": nome_per_sharepoint(nome), "parentReference": {"id": padre_id}, "@microsoft.graph.conflictBehavior": "replace"})


class NonTrovato(ErroreSharePoint):
    """404: chi chiama decide se è un errore (sito sbagliato) o un'informazione (cartella da creare)."""
