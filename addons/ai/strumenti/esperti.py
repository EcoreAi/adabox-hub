"""Sotto-agenti: l'assistente principale chiede a un esperto (un altro assistente, con istruzioni, strumenti e
modello propri). Un livello solo; l'esperto lavora in sola lettura in una conversazione interna."""
from .registro import ErroreStrumento, Strumento, registra


def _esperti(utente):
    from ..models import Assistente
    return [a for a in Assistente.objects.filter(attivo=True).order_by("nome") if a.ammesso(utente)]


def elenco_esperti(contesto):
    esperti = _esperti(contesto.utente)
    if not esperti:
        return "Nessun esperto disponibile."
    return [{"esperto": a.nome, "app": a.app or "tutte", "descrizione": a.descrizione} for a in esperti]


def chiedi_esperto(contesto, esperto, domanda):
    from .. import motore
    from ..models import Conversazione, Turno
    if getattr(contesto.turno, "compito", "") == "esperto":
        raise ErroreStrumento("Un esperto non può consultare altri esperti.")
    scelto = next((a for a in _esperti(contesto.utente) if a.nome.lower() == (esperto or "").strip().lower()), None)
    if scelto is None:
        nomi = ", ".join(a.nome for a in _esperti(contesto.utente)) or "nessuno"
        raise ErroreStrumento(f"Esperto «{esperto}» inesistente o non disponibile. Esperti: {nomi}.")
    if not (domanda or "").strip():
        raise ErroreStrumento("Scrivi la domanda per l'esperto, completa di tutto il contesto che gli serve.")
    interna = Conversazione.objects.create(utente=contesto.utente, ambito=scelto.app, assistente=scelto, nascosta=True,
                                           titolo=f"Esperto: {scelto.nome}"[:120], titolo_generato=True)
    turno = motore.avvia(interna, domanda, contesto.utente, contesto.azienda, compito="esperto", sincrono=True,
                         nota="Ti consulta l'assistente principale, non l'utente: rispondi in modo completo e conciso "
                              "con i dati trovati e i loro link. Non puoi modificare dati.")
    turno.refresh_from_db()
    if turno.stato != Turno.COMPLETATO:
        raise ErroreStrumento(f"L'esperto non ha risposto ({turno.get_stato_display().lower()}): {turno.errore[:300]}")
    return {"esperto": scelto.nome, "risposta": turno.testo}


def _ci_sono_esperti():
    from ..models import Assistente
    return Assistente.objects.filter(attivo=True).exists()


registra(Strumento(
    "elenco_esperti", "Gli esperti (assistenti specializzati, per esempio per un'app) che si possono consultare con "
                      "chiedi_esperto, con a cosa servono.", {"type": "object", "properties": {}, "required": []},
    elenco_esperti, disponibile=_ci_sono_esperti))
registra(Strumento(
    "chiedi_esperto", "Passa una domanda a un esperto e restituisce la sua risposta: l'esperto ha istruzioni, strumenti e "
                      "modello propri e lavora in sola lettura. Scrivi una domanda completa e autosufficiente; più "
                      "esperti si possono consultare insieme.",
    {"type": "object", "properties": {"esperto": {"type": "string", "description": "nome come in elenco_esperti"},
                                      "domanda": {"type": "string"}},
     "required": ["esperto", "domanda"]}, chiedi_esperto, timeout=300, disponibile=_ci_sono_esperti))
