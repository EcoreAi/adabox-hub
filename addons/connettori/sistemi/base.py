"""Ciò che vale per tutti i sistemi esterni: gli errori, i tre tipi di record e il contratto di un connettore.

Il motore (sincronia.py) parla solo con questo contratto; ogni sistema (HubSpot, Salesforce, Zoho) lo traduce nelle
sue chiamate e nei suoi nomi di campo. I record che un connettore restituisce sono dizionari con almeno "id"; il resto
è nel formato del sistema e lo legge solo il suo connettore."""
import datetime
from urllib.parse import urlsplit

PERSONE, AZIENDE, OPPORTUNITA = "contacts", "companies", "deals"      # i nomi di HubSpot, il primo sistema: restano le chiavi
TIPI = (PERSONE, AZIENDE, OPPORTUNITA)


class ErroreConnettore(RuntimeError):
    """Serve una persona: credenziali sbagliate, dato rifiutato. Ritentare non aiuta."""


class ErroreTemporaneo(ErroreConnettore):
    """Rete, troppe richieste, server in difficoltà: si riprova più tardi."""


class Sistema:
    """Il contratto di un connettore. `trova` restituisce l'id, None se non c'è o False se la chiave porta a più record
    (non si sceglie a caso). Le chiavi di ricerca sono "email" (persone), "dominio" e "nome" (aziende)."""
    nome = ""
    etichetta = ""

    def verifica(self):
        raise NotImplementedError

    def modificati(self, tipo, da, dopo=None):
        """(record, prossima pagina): i record di un tipo cambiati da `da` (datetime), dal meno recente."""
        raise NotImplementedError

    def istante(self, tipo, record):
        """Quando è cambiato il record (datetime con fuso), per far avanzare il cursore."""
        raise NotImplementedError

    def associazioni(self, tipo, verso, record):
        """{id: [id associati di tipo `verso`]} per una pagina di record."""
        raise NotImplementedError

    def trova(self, tipo, chiave, valore):
        raise NotImplementedError

    def crea(self, tipo, dati):
        raise NotImplementedError

    def aggiorna(self, tipo, id_esterno, dati):
        raise NotImplementedError

    def associa(self, tipo, id_esterno, verso, id_verso):
        raise NotImplementedError

    def fasi(self):
        """Le fasi delle opportunità: [{id, label, ordine, probabilita (0-1), chiusa, vinta}]."""
        raise NotImplementedError

    def in_adabox(self, tipo, record, fasi=None):
        """I campi di adabox dal record esterno; i vuoti restano fuori: non cancellano ciò che c'è da noi. Per le
        opportunità c'è anche "fase_esterna", la fase del record tra quelle date."""
        raise NotImplementedError

    def fuori(self, tipo, obj, fase=None):
        """I campi del sistema esterno dal record di adabox (contatto od opportunità, con la fase esterna scelta)."""
        raise NotImplementedError


class Deposito:
    """Dove un connettore tiene il token di accesso tra un lavoro e l'altro (cifrato sul collegamento). Senza
    deposito il token vive quanto il client."""

    def leggi(self):
        return None

    def salva(self, token, scade):
        pass


# --- aiuti comuni ai connettori ----------------------------------------------------------------------------------

def pulisci(dati):
    return {k: str(v).strip() for k, v in dati.items() if v is not None and str(v).strip()}


def pieni(dati):
    return {k: v for k, v in dati.items() if v}


def dominio(sito):
    """«https://www.rossi.it/chi-siamo» → «rossi.it»: la chiave con cui si riconoscono le aziende."""
    sito = (sito or "").strip().lower()
    if not sito:
        return ""
    try:
        host = urlsplit(sito if "://" in sito else f"https://{sito}").hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def nome_e_cognome(nome):
    """Si separa sul primo spazio, l'unica divisione che non inventa nulla."""
    primo, _, resto = (nome or "").strip().partition(" ")
    return primo, resto


def nazione(valore):
    valore = (valore or "").strip()
    return valore.upper() if len(valore) == 2 and valore.isalpha() else None


def data(testo):
    """La data di un valore esterno: ISO («2026-11-30T00:00:00Z» o «2026-11-30») oppure millisecondi."""
    testo = str(testo or "").strip()
    if not testo:
        return None
    if testo.isdigit():
        return datetime.datetime.fromtimestamp(int(testo) / 1000, tz=datetime.timezone.utc).date()
    try:
        return datetime.date.fromisoformat(testo[:10])
    except ValueError:
        return None
