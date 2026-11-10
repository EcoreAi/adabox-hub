"""Ciò che vale per Google e Microsoft: gli errori, il flusso OAuth con PKCE, il token di accesso tenuto sulla casella
e il contratto che leggono posta.py e agenda.py.

Eventi normalizzati: {"id", "titolo", "inizio", "fine" (datetime con fuso; per la giornata intera la mezzanotte
locale del primo e dell'ultimo giorno), "tutto_il_giorno", "luogo", "descrizione", "partecipanti" (email),
"aggiornato", "saltare" (ricorrenti e annullati: non passano)}."""
import base64
import datetime
import hashlib
import json
from urllib.parse import urlencode

import httpx2 as httpx
from django.utils import timezone

from core import cifratura

TEMPO = 20


class ErrorePosta(RuntimeError):
    """Serve la persona: accesso revocato, permessi mancanti. Ritentare non aiuta: va ricollegata la casella."""


class ErroreTemporaneo(ErrorePosta):
    """Rete, troppe richieste, servizio in difficoltà: si riprova al prossimo giro."""


def sfida(verificatore):
    return base64.urlsafe_b64encode(hashlib.sha256(verificatore.encode()).digest()).rstrip(b"=").decode()


def affermazioni(id_token):
    """Le affermazioni dell'id_token senza verificarne la firma: arriva direttamente dal servizio su TLS, in risposta
    al nostro codice (OpenID Connect Core 3.1.3.7 lo ammette). Serve solo a sapere l'indirizzo della casella."""
    try:
        corpo = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
    except (AttributeError, IndexError, ValueError):
        return {}


def mezzanotte(giorno):
    return timezone.make_aware(datetime.datetime.combine(giorno, datetime.time()))


class Fornitore:
    tipo = etichetta = ""
    AUTORIZZA = TOKEN = ""
    AMBITI = ()

    def __init__(self, servizio, casella=None, transport=None):
        self.servizio, self.casella = servizio, casella
        self.http = httpx.Client(timeout=TEMPO, transport=transport, trust_env=False, follow_redirects=False)
        self._accesso = None

    # --- collegamento (OAuth con PKCE) -----------------------------------------------------------------------------

    def parametri_autorizzazione(self):
        return {}

    def url_autorizzazione(self, redirect_uri, stato, verificatore):
        parametri = {"client_id": self.servizio.client_id, "response_type": "code", "redirect_uri": redirect_uri, "scope": " ".join(self.AMBITI),
                     "state": stato, "code_challenge": sfida(verificatore), "code_challenge_method": "S256", **self.parametri_autorizzazione()}
        return f"{self.AUTORIZZA}?{urlencode(parametri)}"

    def _token_endpoint(self, dati):
        try:
            r = self.http.post(self.TOKEN, data={"client_id": self.servizio.client_id, "client_secret": self.servizio.segreto(), **dati},
                               headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise ErroreTemporaneo(f"{self.etichetta} non raggiungibile: {type(e).__name__}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise ErroreTemporaneo(f"{self.etichetta} risponde {r.status_code}: si riprova più tardi")
        try:
            corpo = r.json()
        except ValueError:
            corpo = {}
        if r.status_code >= 400 or not corpo.get("access_token"):
            raise ErrorePosta(f"{self.etichetta} non dà l'accesso ({str(corpo.get('error', r.status_code))[:60]}): ricollega la casella.")
        return corpo

    def scambia(self, codice, redirect_uri, verificatore):
        """Dopo il ritorno dal servizio: {"refresh", "accesso", "scade", "email"}."""
        corpo = self._token_endpoint({"grant_type": "authorization_code", "code": codice, "redirect_uri": redirect_uri,
                                      "code_verifier": verificatore})
        if not corpo.get("refresh_token"):
            raise ErrorePosta(f"{self.etichetta} non ha dato l'accesso permanente: togli l'app dal tuo account e ricollega.")
        self._accesso = corpo["access_token"]
        return {"refresh": corpo["refresh_token"], "accesso": corpo["access_token"], "scade": self._scadenza(corpo),
                "email": self.indirizzo(corpo)}

    def indirizzo(self, corpo):
        raise NotImplementedError

    @staticmethod
    def _scadenza(corpo):
        return timezone.now() + datetime.timedelta(seconds=max(int(corpo.get("expires_in") or 3600) - 120, 60))

    # --- accesso tenuto sulla casella ----------------------------------------------------------------------------------

    def _token(self, nuovo=False):
        c = self.casella
        if self._accesso and not nuovo:
            return self._accesso
        if not nuovo and c.accesso_cifrato and c.accesso_scade and c.accesso_scade > timezone.now():
            try:
                self._accesso = cifratura.decifra(c.accesso_cifrato)
                return self._accesso
            except Exception:               # chiave cambiata: se ne chiede uno nuovo
                pass
        corpo = self._token_endpoint({"grant_type": "refresh_token", "refresh_token": c.refresh_token()})
        self._accesso = corpo["access_token"]
        c.accesso_cifrato, c.accesso_scade = cifratura.cifra(self._accesso), self._scadenza(corpo)
        campi = {"accesso_cifrato": c.accesso_cifrato, "accesso_scade": c.accesso_scade}
        if corpo.get("refresh_token"):                       # Microsoft lo rinnova a ogni uso
            c.refresh_cifrato = campi["refresh_cifrato"] = cifratura.cifra(corpo["refresh_token"])
        type(c).objects.filter(pk=c.pk).update(**campi)
        return self._accesso

    def _chiama(self, metodo, url, ripeti=True, headers=None, **kwargs):
        try:
            r = self.http.request(metodo, url, headers={"Authorization": f"Bearer {self._token()}", **(headers or {})}, **kwargs)
        except httpx.HTTPError as e:
            raise ErroreTemporaneo(f"{self.etichetta} non raggiungibile: {type(e).__name__}") from e
        if r.status_code == 401 and ripeti:
            self._token(nuovo=True)
            return self._chiama(metodo, url, ripeti=False, headers=headers, **kwargs)
        if r.status_code == 429 or r.status_code >= 500:
            raise ErroreTemporaneo(f"{self.etichetta} risponde {r.status_code}: si riprova più tardi")
        if r.status_code in (401, 403):
            raise ErrorePosta(f"{self.etichetta} rifiuta l'accesso ({r.status_code}): ricollega la casella e accetta i permessi richiesti.")
        if r.status_code >= 400:
            raise ErrorePosta(f"{self.etichetta} risponde {r.status_code}: {self._messaggio(r)[:200]}")
        return r

    @staticmethod
    def _messaggio(r):
        try:
            corpo = r.json()
        except ValueError:
            return ""
        errore = corpo.get("error") if isinstance(corpo, dict) else None
        return str(errore.get("message", "")) if isinstance(errore, dict) else str(errore or "")

    # --- il contratto --------------------------------------------------------------------------------------------------

    def messaggi(self, dal, dopo=None):
        """([{"id", "indirizzi" (mittente e destinatari), "quando"}], prossima pagina): i messaggi arrivati o
        partiti da `dal`, senza scaricarli."""
        raise NotImplementedError

    def grezza(self, id_esterno):
        """Il messaggio intero (RFC 822) in bytes."""
        raise NotImplementedError

    def eventi(self, dal, dopo=None):
        """([evento normalizzato], prossima pagina): gli eventi del calendario principale cambiati da `dal`."""
        raise NotImplementedError

    def crea_evento(self, dati):
        raise NotImplementedError

    def aggiorna_evento(self, id_esterno, dati):
        raise NotImplementedError
