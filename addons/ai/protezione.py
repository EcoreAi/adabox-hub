"""Protezione dei dati personali verso i modelli cloud, con il servizio adabox-pii.

Il log degli eventi resta in chiaro (è nel nostro database). A ogni chiamata a un modello non locale i messaggi si
mascherano: i dati personali diventano segnaposto stabili per conversazione ([FULLNAME_1], [IBAN_1]...). La risposta
torna in chiaro prima di arrivare all'utente, al log e agli strumenti: testo in streaming, argomenti delle chiamate,
blocchi finali. Se il servizio non risponde, quell'anello della catena fallisce: niente testo in chiaro al cloud.
"""
import hashlib
import json
import logging
import re
import threading
import urllib.request
from collections import OrderedDict

from .gateway.tipi import ChiamataStrumento, ErroreModello, Fine, Testo

log = logging.getLogger("ai.protezione")

TIMEOUT = 30
MAX_CACHE = 2000
ESCLUSI_DEFAULT = "DATE,TIME,AMOUNT,AGE,GENDER"
ISTRUZIONE = (
    "\n\nProtezione dei dati: alcuni dati personali (nomi, codici fiscali, IBAN, email, indirizzi...) ti arrivano "
    "come segnaposto tra parentesi quadre, es. [FULLNAME_1] o [EMAIL_2]. Ogni segnaposto indica sempre lo stesso "
    "valore: usalo così com'è nelle risposte e negli argomenti degli strumenti (l'utente vedrà il valore vero) e non "
    "chiedere di rivelarlo. Nei link Markdown lascia il segnaposto con le parentesi: [testo]([URL_1]).")
SEGNAPOSTO = re.compile(r"\[\s*([A-Za-z]+(?:_[A-Za-z]+)*)[\s_]+(\d+)\s*\]")
LINK_SENZA_QUADRE = re.compile(r"\]\(\s*([A-Z]+(?:_[A-Z]+)*)_(\d+)\s*\)")
CHIAVE_JSON = re.compile(r'^"\s*:')
PAROLE = frozenset({"FULLNAME", "USERNAME", "ORG", "CITY", "PROVINCE"})
NUMERICHE = frozenset({"TELEPHONENUM", "CREDITCARDNUMBER", "IBAN", "CF", "PIVA", "IPADDR", "POD", "PDR", "DEVICE_ID",
                       "EMPLOYEE_ID", "ID_DOC", "BUSINESS_CODE", "SECRET", "TARGA", "CATASTO", "BUILDINGNUM",
                       "ZIPCODE", "DOCID", "DATE", "TIME", "AMOUNT", "AGE"})

_cache = OrderedDict()                          # sha1(testo + esclusi) -> [(inizio, fine, etichetta)]
_cache_lock = threading.Lock()


class ServizioNonDisponibile(Exception):
    pass


# ---------- servizio ----------

def impostazioni():
    from core import parametri
    try:
        url = (parametri.leggi("ai.url_pii") or "").strip().rstrip("/")
        esclusi = parametri.leggi("ai.pii_escludi")
    except KeyError:                                   # impostazioni non dichiarate (modulo non installato)
        return "", ()
    esclusi = ESCLUSI_DEFAULT if esclusi is None else esclusi
    return url, tuple(sorted({e.strip().upper() for e in str(esclusi).split(",") if e.strip()}))


def _analizza(url, testo, esclusi):
    """[(inizio, fine, etichetta)] sulle posizioni di `testo`. Il servizio lavora sul testo senza spazi ai bordi e,
    senza `include_mapping`, toglie il testo originale dai segmenti: si chiede e si controlla che i segmenti
    ricostruiscano esattamente il testo inviato (il valore in chiaro resta sulla rete interna)."""
    if not testo.strip():
        return []
    richiesta = urllib.request.Request(f"{url}/analyze", headers={"Content-Type": "application/json"},
                                       data=json.dumps({"text": testo, "exclude_tags": list(esclusi),
                                                        "include_mapping": True}).encode())
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            segmenti = json.load(risposta)["segments"]
    except Exception as e:
        raise ServizioNonDisponibile(str(e)) from e
    inizio = len(testo) - len(testo.lstrip())
    spans, posizione = [], inizio
    for segmento in segmenti:
        pezzo = segmento.get("t")
        if pezzo is None:
            raise ServizioNonDisponibile("segmento senza testo originale")
        if segmento.get("label"):
            spans.append((posizione, posizione + len(pezzo), segmento["label"]))
        posizione += len(pezzo)
    if posizione - inizio != len(testo.strip()):
        raise ServizioNonDisponibile("i segmenti non ricostruiscono il testo inviato")
    return spans


def spans(url, testo, esclusi):
    """Gli span dei dati personali di un testo (con cache: la storia si rimaschera a ogni chiamata)."""
    chiave = hashlib.sha1(("|".join(esclusi) + "\0" + testo).encode()).hexdigest()
    with _cache_lock:
        if chiave in _cache:
            _cache.move_to_end(chiave)
            return _cache[chiave]
    risultato = _analizza(url, testo, esclusi)
    with _cache_lock:
        _cache[chiave] = risultato
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)
    return risultato


def _numerico(valore):
    cifre = "".join(c for c in valore if c not in " .,/-+")
    return bool(cifre) and cifre.isdigit()


def _sembra_codice(valore, etichetta):
    v = valore.strip()
    if any(c.isdigit() for c in v):
        return True
    if " " in v:
        return False
    if any(c in "_/.\\#:" for c in v):
        return True
    if "-" in v and any(parte.isupper() and len(parte) >= 2 for parte in v.split("-")):     # SYN-KIT, non Anna-Maria
        return True
    return etichetta in ("ORG", "USERNAME") and v.isupper() and len(v) <= 4


def plausibile(testo, inizio, fine, etichetta):
    """Scarta le rilevazioni tipiche dei risultati degli strumenti: chiavi JSON, codici presi per nomi, numeri presi
    per dati personali di tipo "a parole"."""
    valore = testo[inizio:fine]
    if inizio > 0 and testo[inizio - 1] == '"' and CHIAVE_JSON.match(testo[fine:fine + 4]):
        return False
    if etichetta not in NUMERICHE and _numerico(valore):
        return False
    if etichetta in PAROLE and _sembra_codice(valore, etichetta):
        return False
    return bool(valore.strip())


# ---------- segnaposto ----------

class Vault:
    """Segnaposto ↔ valore di una conversazione: lo stesso valore (maiuscole e spazi a parte) ha sempre lo stesso
    segnaposto, anche con etichette diverse."""

    def __init__(self, mappa=None):
        self.mappa = dict(mappa or {})                       # "[FULLNAME_1]" -> "Mario Rossi"
        self._per_valore = {self._norma(v): s for s, v in self.mappa.items()}
        self._contatori = {}
        for s in self.mappa:
            m = SEGNAPOSTO.fullmatch(s)
            if m:
                self._contatori[m.group(1)] = max(self._contatori.get(m.group(1), 0), int(m.group(2)))
        self.nuovi = 0

    @staticmethod
    def _norma(valore):
        return " ".join(valore.split()).casefold()

    def segnaposto(self, etichetta, valore):
        chiave = self._norma(valore)
        if chiave not in self._per_valore:
            etichetta = etichetta.upper()
            self._contatori[etichetta] = self._contatori.get(etichetta, 0) + 1
            s = f"[{etichetta}_{self._contatori[etichetta]}]"
            self._per_valore[chiave], self.mappa[s] = s, valore
            self.nuovi += 1
        return self._per_valore[chiave]

    def smaschera(self, testo):
        """(testo in chiaro, segnaposto sconosciuti) — tollera [fullname 1], [ FULLNAME_1 ] e i link senza quadre."""
        sconosciuti = 0

        def valore(etichetta, numero, originale):
            nonlocal sconosciuti
            s = f"[{etichetta.upper()}_{numero}]"
            if s in self.mappa:
                return self.mappa[s]
            sconosciuti += 1
            return originale
        testo = LINK_SENZA_QUADRE.sub(lambda m: "](" + valore(m.group(1), m.group(2), m.group(0)[2:-1]) + ")", testo)
        testo = SEGNAPOSTO.sub(lambda m: valore(m.group(1), m.group(2), m.group(0)), testo)
        return testo, sconosciuti


def maschera_testo(testo, vault, url, esclusi):
    if not testo or not testo.strip():
        return testo, 0
    pezzi, posizione, trovati = [], 0, 0
    for inizio, fine, etichetta in sorted(spans(url, testo, esclusi)):
        if inizio < posizione or not plausibile(testo, inizio, fine, etichetta):
            continue
        pezzi.append(testo[posizione:inizio])
        pezzi.append(vault.segnaposto(etichetta, testo[inizio:fine]))
        posizione, trovati = fine, trovati + 1
    pezzi.append(testo[posizione:])
    return "".join(pezzi), trovati


def _mappa_stringhe(valore, funzione):
    if isinstance(valore, str):
        return funzione(valore)
    if isinstance(valore, list):
        return [_mappa_stringhe(v, funzione) for v in valore]
    if isinstance(valore, dict):
        return {k: _mappa_stringhe(v, funzione) for k, v in valore.items()}
    return valore


# ---------- protezione di una chiamata ----------

class Protezione:
    """Una per turno: sa se un modello va protetto, maschera la richiesta e smaschera ciò che torna."""

    def __init__(self, conversazione=None, url=None, esclusi=None):
        self._url, self._esclusi = url, esclusi             # None = dalle impostazioni, lette solo se servono
        self.conversazione = conversazione
        self.vault = Vault(getattr(conversazione, "segnaposto", None))
        self.protetti = set()                                # segnaposto usati in questo turno
        self.sconosciuti = 0
        self.ultima_mascherata = False

    def _impostazioni(self):
        if self._url is None:
            self._url, self._esclusi = impostazioni()
        return self._url, tuple(self._esclusi or ())

    @property
    def url(self):
        return self._impostazioni()[0]

    @property
    def esclusi(self):
        return self._impostazioni()[1]

    @property
    def attiva(self):
        return bool(self.url)

    def serve(self, modello):
        return not modello.provider.locale and self.attiva

    def _testo(self, testo):
        mascherato, _ = maschera_testo(testo, self.vault, self.url, self.esclusi)
        for etichetta, numero in SEGNAPOSTO.findall(mascherato):
            if f"[{etichetta}_{numero}]" in self.vault.mappa:
                self.protetti.add(f"[{etichetta}_{numero}]")
        return mascherato

    def _con_valori_noti(self, testo):
        """Negli argomenti delle chiamate passate: i valori già nel vault tornano segnaposto (senza servizio)."""
        for s, v in sorted(self.vault.mappa.items(), key=lambda x: -len(x[1])):
            if len(v) >= 3 and v in testo:
                testo = testo.replace(v, s)
        return testo

    def richiesta(self, richiesta, mascherata):
        """La richiesta per un anello: mascherata (modelli cloud) o in chiaro, con i blocchi nativi coerenti."""
        messaggi = []
        for m in richiesta["messaggi"]:
            if m["ruolo"] == "assistente" and m.get("nativo") and bool(m.get("mascherato")) != mascherata:
                m = {k: v for k, v in m.items() if k != "nativo"}           # prodotti con l'altra politica
            messaggi.append(m)
        if not mascherata:
            return {**richiesta, "messaggi": messaggi}
        try:
            protetti = [self._messaggio(m) for m in messaggi]
        except ServizioNonDisponibile as e:
            log.warning("servizio PII non disponibile: %s", e)
            raise ErroreModello("PII", "il servizio di protezione dei dati personali non risponde")
        self._salva()
        return {**richiesta, "sistema": richiesta["sistema"] + ISTRUZIONE, "messaggi": protetti}

    def _messaggio(self, m):
        if m["ruolo"] == "utente":
            return {**m, "testo": self._testo(m["testo"])}
        if m["ruolo"] == "strumento":
            return {**m, "risultati": [{**r, "contenuto": self._testo(r["contenuto"])} for r in m["risultati"]]}
        if m.get("nativo"):                                  # già mascherato quando il modello l'ha scritto
            return m
        blocchi = []
        for b in m["blocchi"]:
            if b["tipo"] == "testo":
                blocchi.append({**b, "testo": self._testo(b["testo"])})
            else:
                blocchi.append({**b, "argomenti": _mappa_stringhe(b["argomenti"], self._con_valori_noti)})
        return {**m, "blocchi": blocchi}

    def _salva(self):
        if self.conversazione is not None and self.vault.nuovi and self.conversazione.pk:
            type(self.conversazione).objects.filter(pk=self.conversazione.pk).update(segnaposto=self.vault.mappa)
            self.conversazione.segnaposto = dict(self.vault.mappa)
            self.vault.nuovi = 0

    def smaschera(self, testo):
        chiaro, sconosciuti = self.vault.smaschera(testo)
        self.sconosciuti += sconosciuti
        return chiaro

    def flusso(self, pezzi):
        """I pezzi di un modello protetto, in chiaro. Il testo da un «[» aperto resta nel buffer finché il segnaposto
        non si chiude (o supera 40 caratteri): un segnaposto può arrivare spezzato su più pezzi."""
        buffer = ""
        for pezzo in pezzi:
            if isinstance(pezzo, Testo):
                buffer += pezzo.testo
                trattieni = None
                aperta = buffer.rfind("[")
                if aperta >= 0 and "]" not in buffer[aperta:] and len(buffer) - aperta <= 40:
                    trattieni = aperta
                link = buffer.rfind("](")
                if link >= 0 and ")" not in buffer[link:] and len(buffer) - link <= 40:
                    trattieni = link if trattieni is None else min(trattieni, link)
                pronto, buffer = (buffer[:trattieni], buffer[trattieni:]) if trattieni is not None else (buffer, "")
                if pronto:
                    yield Testo(self.smaschera(pronto))
                continue
            if buffer:
                yield Testo(self.smaschera(buffer))
                buffer = ""
            if isinstance(pezzo, ChiamataStrumento):
                yield ChiamataStrumento(pezzo.id, pezzo.nome, _mappa_stringhe(pezzo.argomenti, self.smaschera))
            elif isinstance(pezzo, Fine):
                blocchi = [{**b, "testo": self.smaschera(b["testo"])} if b["tipo"] == "testo" else
                           {**b, "argomenti": _mappa_stringhe(b["argomenti"], self.smaschera)} for b in pezzo.blocchi]
                yield Fine(pezzo.motivo, blocchi, pezzo.nativo)
            else:
                yield pezzo
        if buffer:
            yield Testo(self.smaschera(buffer))
