"""SDK Python generato dallo schema dell'API: un solo file, senza dipendenze (solo la libreria standard), con una
risorsa per ogni vista (client.vendite.ordini.lista(), .leggi(), .crea(), .modifica(), .elimina(), .azione(), .tutti()),
i campi di ogni risorsa nella docstring, gli errori come eccezioni e l'attesa automatica quando si supera il limite."""
import keyword
import re

from django.conf import settings

from core import __version__

INTESTAZIONE = '''"""Client Python per l'API di {marchio} ({sito}), generato il {quando} dall'istanza (versione {versione}).

    from adabox import Adabox
    client = Adabox("{sito}", token="…")          # il token si crea in Profilo → Token API
    for ordine in client.vendite.ordini.tutti(q="rossi"):
        print(ordine["id"], ordine["cliente_display"])
    client.vendite.ordini.azione(12, "conferma")

Solo libreria standard. Errori: ErroreApi (con .stato e .dati); 422 → ErroreValidazione con .errori per campo.
Con 429 (troppe richieste) aspetta quanto dice Retry-After e riprova, fino a `tentativi` volte.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class ErroreApi(Exception):
    def __init__(self, stato, dati):
        super().__init__(f"HTTP {{stato}}: {{dati}}")
        self.stato, self.dati = stato, dati


class ErroreValidazione(ErroreApi):
    @property
    def errori(self):
        return (self.dati or {{}}).get("errori", {{}})


class Risorsa:
    """Una vista dell'API: /api/v1/<modulo>/<slug>/."""
    percorso = ""

    def __init__(self, client):
        self._c = client

    def lista(self, q="", o="", p=1, per_page=50, **filtri):
        """Una pagina: {{"count", "page", "per_page", "results"}}. I filtri sono quelli delle liste (es. f_stato="aperta")."""
        return self._c.richiesta("GET", self.percorso, parametri={{"q": q, "o": o, "p": p, "per_page": per_page, **filtri}})

    def tutti(self, per_page=200, **kw):
        """Tutti i record, una pagina dopo l'altra."""
        p = 1
        while True:
            pagina = self.lista(p=p, per_page=per_page, **kw)
            yield from pagina["results"]
            if p * pagina["per_page"] >= pagina["count"]:
                return
            p += 1

    def leggi(self, pk):
        return self._c.richiesta("GET", f"{{self.percorso}}{{pk}}/")

    def crea(self, dati):
        return self._c.richiesta("POST", self.percorso, dati)

    def modifica(self, pk, dati):
        """Solo i campi dati cambiano (PATCH)."""
        return self._c.richiesta("PATCH", f"{{self.percorso}}{{pk}}/", dati)

    def elimina(self, pk):
        return self._c.richiesta("DELETE", f"{{self.percorso}}{{pk}}/")

    def azione(self, pk, nome):
        """Un bottone della pagina di dettaglio (es. "conferma"), con gli stessi permessi."""
        return self._c.richiesta("POST", f"{{self.percorso}}{{pk}}/azioni/{{nome}}/")


class _Modulo:
    pass


class Base:
    def __init__(self, url, token, azienda=None, tentativi=3, timeout=30):
        self.url, self.token, self.azienda, self.tentativi, self.timeout = url.rstrip("/"), token, azienda, tentativi, timeout

    def _apri(self, metodo, url, corpo, intestazioni):
        """Il trasporto HTTP (si sostituisce nei test)."""
        req = urllib.request.Request(url, data=corpo, method=metodo, headers=intestazioni)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def richiesta(self, metodo, percorso, dati=None, parametri=None):
        url = f"{{self.url}}/api/v1/{{percorso}}"
        if parametri:
            url += "?" + urllib.parse.urlencode({{k: v for k, v in parametri.items() if v not in ("", None)}})
        intestazioni = {{"Authorization": f"Bearer {{self.token}}", "Accept": "application/json"}}
        if self.azienda:
            intestazioni["X-Azienda"] = str(self.azienda)
        corpo = None
        if dati is not None:
            corpo = json.dumps(dati).encode()
            intestazioni["Content-Type"] = "application/json"
        for tentativo in range(self.tentativi + 1):
            stato, risposta_int, testo = self._apri(metodo, url, corpo, intestazioni)
            if stato == 429 and tentativo < self.tentativi:
                attesa = {{k.lower(): v for k, v in risposta_int.items()}}.get("retry-after", "1")
                time.sleep(min(int(attesa) if str(attesa).isdigit() else 1, 60))
                continue
            break
        dati_risposta = json.loads(testo) if testo else None
        if stato == 422:
            raise ErroreValidazione(stato, dati_risposta)
        if stato >= 400:
            raise ErroreApi(stato, dati_risposta)
        return dati_risposta

    def me(self):
        """Utente, aziende e app visibili."""
        return self.richiesta("GET", "me/")
'''

RISORSA = '''

class {classe}(Risorsa):
    """{titolo}

    Campi: {campi}
    """
    percorso = "{percorso}"
'''


def _nome(testo):
    nome = re.sub(r"\W", "_", testo)
    if nome[:1].isdigit() or keyword.iskeyword(nome):
        nome = f"_{nome}"
    return nome


def genera(schema):
    """Il sorgente dell'SDK dallo schema OpenAPI di /api/v1/openapi.json."""
    from django.utils import timezone
    risorse = {}                                             # modulo -> {slug: (titolo, campi)}
    for percorso, operazioni in schema.get("paths", {}).items():
        trovato = re.fullmatch(r"/api/v1/([\w-]+)/([\w-]+)/", percorso)
        if not trovato or "get" not in operazioni or "post" not in operazioni:
            continue
        modulo, slug = trovato.groups()
        risposte = operazioni["get"].get("responses", {})
        record = ((risposte.get("200") or risposte.get(200) or {}).get("content", {})
                  .get("application/json", {}).get("schema", {}).get("properties", {}).get("results", {}).get("items", {}))
        campi = [f"{k} ({v.get('title', '')})" if v.get("title") else k for k, v in record.get("properties", {}).items()]
        titolo = operazioni["get"].get("summary", slug)
        risorse.setdefault(modulo, {})[slug] = (titolo, campi)
    sorgente = [INTESTAZIONE.format(marchio=settings.THEME.get("brand", "adabox"), sito=settings.SITO_URL,
                                    quando=timezone.localdate().isoformat(), versione=__version__)]
    for modulo, viste in sorted(risorse.items()):
        for slug, (titolo, campi) in sorted(viste.items()):
            sorgente.append(RISORSA.format(classe=f"R_{_nome(modulo)}_{_nome(slug)}", titolo=titolo.replace('"', "'"),
                                           campi=", ".join(campi).replace('"', "'") or "—", percorso=f"{modulo}/{slug}/"))
    righe = ["\n\nclass Adabox(Base):", '    """Il client: una proprietà per modulo, una risorsa per vista (client.vendite.ordini)."""',
             "", "    def __init__(self, *args, **kwargs):", "        super().__init__(*args, **kwargs)"]
    for modulo, viste in sorted(risorse.items()):
        righe.append(f"        self.{_nome(modulo)} = _Modulo()")
        for slug in sorted(viste):
            righe.append(f"        self.{_nome(modulo)}.{_nome(slug)} = R_{_nome(modulo)}_{_nome(slug)}(self)")
    sorgente.append("\n".join(righe) + "\n")
    return "".join(sorgente)
