"""Google e Microsoft finti, con il loro formato: token, posta (elenco, metadati, messaggio grezzo) e calendario.
Tengono lo stato in memoria e contano le chiamate, così i test vedono che cosa è stato scaricato."""
import base64
import datetime
import json
import re
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import format_datetime, getaddresses
from urllib.parse import parse_qs, unquote

import httpx2 as httpx


def id_token(email):
    corpo = base64.urlsafe_b64encode(json.dumps({"email": email, "sub": "123"}).encode()).rstrip(b"=").decode()
    return f"e30.{corpo}.firma"


def messaggio(da, a, oggetto="Preventivo", testo="Ciao, ecco il preventivo.", cc=(), message_id=None, quando=None, allegato=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = da, ", ".join(a), oggetto
    if cc:
        m["Cc"] = ", ".join(cc)
    m["Message-ID"] = message_id or f"<{abs(hash((da, oggetto, testo)))}@esempio.it>"
    m["Date"] = format_datetime(quando or datetime.datetime.now(datetime.timezone.utc))
    m.set_content(testo)
    if allegato:
        m.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename="offerta.pdf")
    return m


class Finto:
    def __init__(self, email):
        self.email = email
        self.posta = {}                 # id -> (EmailMessage, ms, etichette)
        self.eventi = {}                # id -> dict nel formato del servizio
        self.scaricati = []             # id dei messaggi scaricati per intero
        self.accesso, self.refresh, self.rinnovi = "acc-1", "ref-1", 0
        self.revocato = False
        self.chiamate = []
        self.inviati = []               # messaggi spediti dalla casella (email.message.EmailMessage)
        self.invio_rifiutato = False

    def aggiungi(self, id_esterno, msg, quando=None, etichette=()):
        quando = quando or datetime.datetime.now(datetime.timezone.utc)
        self.posta[id_esterno] = (msg, int(quando.timestamp() * 1000), list(etichette))

    def trasporto(self):
        def gestore(r):
            self.chiamate.append(r)
            return self.rispondi(r)
        return httpx.MockTransport(gestore)

    def _token(self, r):
        dati = parse_qs(r.content.decode())
        if self.revocato:
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
        if dati.get("grant_type") == ["authorization_code"]:
            assert dati.get("code_verifier"), "manca il verificatore PKCE"
            return httpx.Response(200, json={"access_token": self.accesso, "refresh_token": self.refresh, "expires_in": 3599,
                                             "id_token": id_token(self.email)})
        assert dati.get("refresh_token") == [self.refresh], dati
        self.rinnovi += 1
        self.accesso = f"acc-{self.rinnovi + 1}"
        return httpx.Response(200, json=self._rinnovato())

    def _rinnovato(self):
        return {"access_token": self.accesso, "expires_in": 3599}

    def _autorizzato(self, r):
        return r.headers.get("Authorization") == f"Bearer {self.accesso}"


class FintoGoogle(Finto):
    def rispondi(self, r):
        url = r.url
        if url.host == "oauth2.googleapis.com" and url.path == "/token":
            return self._token(r)
        if not self._autorizzato(r):
            return httpx.Response(401, json={"error": {"code": 401, "message": "Invalid Credentials"}})
        if url.path == "/gmail/v1/users/me/messages/send":
            if self.invio_rifiutato:
                return httpx.Response(403, json={"error": {"code": 403, "message": "Request had insufficient authentication scopes."}})
            raw = json.loads(r.content)["raw"]
            self.inviati.append(message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), policy=policy.default))
            return httpx.Response(200, json={"id": "inviato1", "threadId": "t1", "labelIds": ["SENT"]})
        if url.path == "/gmail/v1/users/me/messages":
            dopo = int(re.search(r"after:(\d+)", url.params["q"]).group(1)) * 1000
            ids = [i for i, (_, ms, _) in sorted(self.posta.items(), key=lambda v: -v[1][1]) if ms > dopo]
            inizio, quanti = int(url.params.get("pageToken") or 0), int(url.params["maxResults"])
            corpo = {"messages": [{"id": i, "threadId": i} for i in ids[inizio:inizio + quanti]], "resultSizeEstimate": len(ids)}
            if inizio + quanti < len(ids):
                corpo["nextPageToken"] = str(inizio + quanti)
            return httpx.Response(200, json=corpo)
        if m := re.fullmatch(r"/gmail/v1/users/me/messages/(\w+)", url.path):
            msg, ms, etichette = self.posta[m.group(1)]
            corpo = {"id": m.group(1), "threadId": m.group(1), "labelIds": etichette or ["INBOX"], "internalDate": str(ms)}
            if url.params["format"] == "raw":
                self.scaricati.append(m.group(1))
                corpo["raw"] = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            else:
                richieste = url.params.get_list("metadataHeaders")
                corpo["payload"] = {"headers": [{"name": h, "value": str(msg[h])} for h in richieste if msg[h]]}
            return httpx.Response(200, json=corpo)
        if url.path == "/calendar/v3/calendars/primary/events":
            if r.method == "POST":
                e = json.loads(r.content)
                e["id"], e["updated"], e["status"] = f"g{len(self.eventi) + 1}", _ora(), "confirmed"
                self.eventi[e["id"]] = e
                return httpx.Response(200, json=e)
            da = url.params["updatedMin"]
            voci = sorted((e for e in self.eventi.values() if e["updated"] >= da), key=lambda e: e["updated"])
            return httpx.Response(200, json={"kind": "calendar#events", "items": voci})
        if m := re.fullmatch(r"/calendar/v3/calendars/primary/events/(\w+)", url.path):
            self.eventi[m.group(1)] = {**self.eventi[m.group(1)], **json.loads(r.content), "updated": _ora()}
            return httpx.Response(200, json=self.eventi[m.group(1)])
        return httpx.Response(404, json={"error": {"message": f"non previsto: {r.method} {url.path}"}})

    def evento(self, id_esterno, **campi):
        e = {"id": id_esterno, "status": "confirmed", "summary": "Riunione", "updated": _ora(),
             "start": {"dateTime": "2026-11-20T10:00:00+01:00"}, "end": {"dateTime": "2026-11-20T11:00:00+01:00"}, **campi}
        self.eventi[id_esterno] = e
        return e


class FintoMicrosoft(Finto):
    def _rinnovato(self):
        self.refresh = f"ref-{self.rinnovi + 1}"                  # Microsoft cambia il refresh token a ogni rinnovo
        return {"access_token": self.accesso, "refresh_token": self.refresh, "expires_in": 3599}

    def rispondi(self, r):
        url = r.url
        if url.host == "login.microsoftonline.com":
            assert url.path.endswith("/oauth2/v2.0/token")
            return self._token(r)
        if not self._autorizzato(r):
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken", "message": "Access token has expired"}})
        percorso = unquote(url.path)
        if percorso == "/v1.0/me":
            return httpx.Response(200, json={"mail": self.email.title(), "userPrincipalName": self.email})
        if percorso == "/v1.0/me/sendMail":
            assert r.headers["Content-Type"] == "text/plain"
            self.inviati.append(message_from_bytes(base64.b64decode(r.content), policy=policy.default))
            return httpx.Response(202)
        if percorso == "/v1.0/me/messages":
            if "$skiptoken" in url.params:
                inizio, da = int(url.params["$skiptoken"]), url.params["da"]
            else:
                inizio, da = 0, re.search(r"receivedDateTime ge (\S+)", url.params["$filter"]).group(1)
            limite = datetime.datetime.fromisoformat(da.replace("Z", "+00:00")).timestamp() * 1000
            voci = sorted(((i, v) for i, v in self.posta.items() if v[1] >= limite), key=lambda v: v[1][1])
            pagina = voci[inizio:inizio + int(url.params.get("$top", 50))]
            corpo = {"value": [_graph_msg(i, m, ms) for i, (m, ms, _) in pagina]}
            if inizio + len(pagina) < len(voci):
                corpo["@odata.nextLink"] = f"https://graph.microsoft.com/v1.0/me/messages?$skiptoken={inizio + len(pagina)}&da={da}"
            return httpx.Response(200, json=corpo)
        if m := re.fullmatch(r"/v1.0/me/messages/([\w=-]+)/\$value", percorso):
            self.scaricati.append(m.group(1))
            return httpx.Response(200, content=self.posta[m.group(1)][0].as_bytes())
        if percorso == "/v1.0/me/events":
            if r.method == "POST":
                e = json.loads(r.content)
                e.update(id=f"AAM{len(self.eventi) + 1}", lastModifiedDateTime=_ora(), type="singleInstance", isCancelled=False)
                self.eventi[e["id"]] = e
                return httpx.Response(201, json=e)
            da = re.search(r"lastModifiedDateTime ge (\S+)", url.params["$filter"]).group(1)
            return httpx.Response(200, json={"value": sorted((e for e in self.eventi.values() if e["lastModifiedDateTime"] >= da),
                                                             key=lambda e: e["lastModifiedDateTime"])})
        if m := re.fullmatch(r"/v1.0/me/events/(\w+)", percorso):
            self.eventi[m.group(1)] = {**self.eventi[m.group(1)], **json.loads(r.content), "lastModifiedDateTime": _ora()}
            return httpx.Response(200, json=self.eventi[m.group(1)])
        return httpx.Response(404, json={"error": {"code": "NotFound", "message": f"non previsto: {r.method} {percorso}"}})


def _ora():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _graph_msg(i, m, ms):
    def persone(intestazione):
        return [{"emailAddress": {"address": e, "name": n}} for n, e in getaddresses([str(m[intestazione] or "")]) if e]
    return {"id": i, "receivedDateTime": datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "from": (persone("From") or [None])[0], "toRecipients": persone("To"), "ccRecipients": persone("Cc")}
