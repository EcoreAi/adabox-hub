"""Funzioni attivabili dei moduli: parti di un modulo (la ricerca sul web dell'assistente, la memoria…) che il piano
comprato dal cliente può comprendere o no, senza dividere il modulo in tanti moduli.

Il modulo le dichiara nel manifest («funzioni»: [{chiave, label, help}]) e le usa dove servono: voci di menu e
impostazioni con «funzione», ModelView.funzione, {% if funzioni.ai.memoria %} nei template e funzioni.attiva() nel
codice. Quali sono comprese lo dice la licenza dell'istanza («funzioni»: {slug: [chiavi]}); un modulo che non vi
compare, o un'istanza senza licenza, le ha tutte. Un modulo con una licenza propria (l'assistente AI) registra la sua
fonte con funzioni.fonte().

Come per i moduli, è un deterrente: il codice di una funzione spenta è comunque sul server. Una funzione da
proteggere davvero va in un modulo a sé, che sul server del cliente non arriva."""

_fonti = {}   # slug -> funzione() che restituisce le chiavi comprese (frozenset) o None = tutte


def fonte(slug, funzione):
    """Da chiamare nel ready() dell'app: le funzioni comprese di `slug` le dice `funzione()` invece della licenza."""
    _fonti[slug] = funzione


def comprese(slug):
    """Le chiavi delle funzioni comprese per il modulo (frozenset), o None se le ha tutte."""
    if slug in _fonti:
        return _fonti[slug]()
    from . import licenza
    stato = licenza.attuale()
    if stato.valida and slug in stato.funzioni:
        return stato.funzioni[slug]
    return None


def attiva(slug, chiave):
    """True se la funzione `chiave` del modulo `slug` è compresa. Senza chiave: sempre."""
    if not chiave:
        return True
    insieme = comprese(slug)
    return insieme is None or chiave in insieme


def catalogo(slug):
    """Le funzioni dichiarate nel manifest del modulo: [{chiave, label, help}]."""
    from .registry import modules
    m = modules.manifests_attivi().get(slug)
    return list(m.funzioni) if m else []


class PerPagina:
    """`funzioni` nei template ({% if funzioni.ai.memoria %}): ogni modulo si chiede una volta per pagina."""

    def __init__(self):
        self._moduli = {}

    def __getitem__(self, slug):
        if slug not in self._moduli:
            self._moduli[slug] = _Comprese(comprese(slug))
        return self._moduli[slug]


class _Comprese:
    def __init__(self, insieme):
        self.insieme = insieme

    def __getitem__(self, chiave):
        return self.insieme is None or chiave in self.insieme
