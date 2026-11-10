"""Gli strumenti dell'assistente come li vede la pagina «Strumenti»: a quale funzione appartengono, se sono disponibili
e, se no, perché. Gli strumenti si spengono a mano (StrumentoSpento) per tutta l'istanza o per un'azienda: spegnere
toglie e basta, e a quale funzione della licenza appartiene uno strumento resta nel codice (ai.funzioni), così da
nessuna pagina si aggira la licenza."""
from .models import StrumentoSpento

RISCHI = {"lettura": "lettura", "scrittura": "scrittura (con conferma)", "irreversibile": "irreversibile (con conferma)"}


def spenti(azienda):
    """I nomi degli strumenti spenti a mano per l'azienda: quelli di tutta l'istanza più quelli suoi."""
    from django.db.models import Q
    filtro = Q(azienda__isnull=True) | Q(azienda=azienda) if azienda is not None else Q(azienda__isnull=True)
    return set(StrumentoSpento.objects.filter(filtro).values_list("nome", flat=True))


def _prima_frase(testo):
    frase = (testo or "").split(". ")[0].strip()
    return frase if frase.endswith((".", ")")) else frase + "."


def elenco(azienda):
    """[{nome, descrizione, funzione, app, rischio, permesso, motivi, spento_istanza, spento_azienda}] in ordine di app e
    nome. «motivi» spiega perché uno strumento non è disponibile (vuoto = disponibile)."""
    from core import funzioni
    from core.registry import modules

    from . import funzioni as funzioni_ai
    from .strumenti import registro
    from .strumenti import app as strumenti_app
    strumenti_app.carica()
    catalogo = {f["chiave"]: f["label"] for f in funzioni.catalogo("ai")}
    comprese = funzioni.comprese("ai")
    app_spente = modules.disattivati()
    nomi_app = {slug: m.nav_label or m.name for slug, m in modules.manifests_attivi().items()}
    per_istanza = set(StrumentoSpento.objects.filter(azienda__isnull=True).values_list("nome", flat=True))
    per_azienda = set(StrumentoSpento.objects.filter(azienda=azienda).values_list("nome", flat=True)) if azienda else set()
    righe = []
    for s in sorted(registro._registro.values(), key=lambda s: (s.app, s.nome)):
        funzione = funzioni_ai.di_strumento(s)
        motivi = []
        if comprese is not None and funzione and funzione not in comprese:
            motivi.append("funzione non compresa nella licenza")
        if s.app and s.app in app_spente:
            motivi.append("app spenta")
        try:
            if s.disponibile is not None and not s.disponibile():
                motivi.append("servizio non configurato")
        except Exception:                                # un controllo che fallisce non rompe la pagina
            motivi.append("servizio non raggiungibile")
        if s.nome in per_istanza:
            motivi.append("spento per tutta l'istanza")
        if s.nome in per_azienda:
            motivi.append("spento per questa azienda")
        righe.append({"nome": s.nome, "descrizione": _prima_frase(s.descrizione),
                      "funzione": catalogo.get(funzione, funzione) if funzione else "",
                      "app": nomi_app.get(s.app, s.app) if s.app else "", "rischio": RISCHI.get(s.rischio, s.rischio),
                      "scrive": s.rischio != "lettura", "permesso": s.permesso or "", "motivi": motivi,
                      "spento_istanza": s.nome in per_istanza, "spento_azienda": s.nome in per_azienda})
    return righe


def esiste(nome):
    from .strumenti import registro
    from .strumenti import app as strumenti_app
    strumenti_app.carica()
    return nome in registro._registro
