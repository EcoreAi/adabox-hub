"""Chi vede e chi gestisce un'area di lavoro (ProgettoChat).

- La vede chi l'ha creata e i membri, sempre nella stessa azienda.
- La gestisce solo chi l'ha creata: istruzioni, cartella, app predefinita, record collegati, membri, eliminazione.
- Le chat sono di chi le scrive: gli altri membri vedono solo quelle condivise con l'area, in sola lettura.
- Ognuno ha sempre la sua area personale («Il mio spazio»): privata, non si elimina, il nome si cambia. Ogni chat sta
  in un'area: quelle che restano senza (chi esce da un'area, area eliminata) tornano nell'area personale di chi le ha
  scritte. L'area corrente è quella su cui l'utente sta lavorando: lì nascono le chat nuove.
- Un'area è di una sola azienda e non si sposta; una chat è dell'azienda della sua area. Chi lavora in più aziende vede
  le aree di tutte, ma apre e scrive in quelle dell'azienda corrente (dalle altre si passa con un clic)."""
from django.contrib.auth import get_user_model
from django.db.models import Q

from core.azienda import consentite
from core.registry import modules

from .models import AreaCorrente, Conversazione, MembroArea, ProgettoChat

NOME_PERSONALE = "Il mio spazio"


def personale(utente, azienda):
    """L'area personale dell'utente nell'azienda, creata la prima volta che serve."""
    if azienda is None:
        return None
    area = ProgettoChat.objects.filter(utente=utente, azienda=azienda, personale=True).first()
    return area or ProgettoChat.objects.create(utente=utente, azienda=azienda, personale=True, nome=NOME_PERSONALE)


def corrente(utente, azienda):
    """L'area su cui l'utente sta lavorando (se la vede ancora), altrimenti la sua area personale. Senza la funzione
    «aree_di_lavoro» sempre quella personale: le chat ci stanno comunque, ma l'utente non la vede."""
    from . import funzioni
    if azienda is None:
        return None
    if not funzioni.attiva("aree_di_lavoro"):
        return personale(utente, azienda)
    scelta = AreaCorrente.objects.filter(utente=utente, azienda=azienda).select_related("area").first()
    if scelta is not None and puo_vedere(utente, scelta.area) and scelta.area.azienda_id == azienda.pk:
        return scelta.area
    return personale(utente, azienda)


def imposta_corrente(utente, area):
    if area is not None and puo_vedere(utente, area):
        AreaCorrente.objects.update_or_create(utente=utente, azienda=area.azienda, defaults={"area": area})


def riaccogli(conversazioni):
    """Le chat rimaste senza area tornano nell'area personale di chi le ha scritte (nell'azienda dell'area lasciata)."""
    for c in conversazioni.select_related("utente"):
        azienda = c.progetto.azienda if c.progetto_id else None
        if azienda is None:
            continue
        c.progetto, c.condivisa = personale(c.utente, azienda), False
        c.save(update_fields=["progetto", "condivisa"])


def visibili(utente, azienda):
    if azienda is None:
        return ProgettoChat.objects.none()
    return visibili_in(utente, [azienda])


def visibili_in(utente, aziende):
    """Le aree che l'utente vede in tutte le `aziende` (per chi lavora in più aziende: le altre sue)."""
    return ProgettoChat.objects.filter(azienda__in=aziende).filter(Q(utente=utente) | Q(membri__utente=utente)).distinct()


def azienda_di(oggetto):
    """L'azienda di un'area, o di una chat: quella della sua area (None per le chat vecchie, senza area)."""
    if isinstance(oggetto, ProgettoChat):
        return oggetto.azienda
    return oggetto.progetto.azienda if oggetto.progetto_id else None


def altra_azienda(oggetto, azienda):
    """L'azienda dell'area o della chat se non è `azienda` (la corrente), altrimenti None. Un'area resta della sua
    azienda: ci si lavora solo con quella corrente, altrimenti Ada risponderebbe con i dati dell'altra. Le chat senza
    area e chi non ha un'azienda corrente: None, come prima."""
    sua = azienda_di(oggetto) if azienda is not None else None
    return sua if sua is not None and sua.pk != azienda.pk else None


def aziende_di(utente):
    """Le aziende consentite dell'utente, chieste una volta per richiesta (sull'utente, come modules.aziende_ammesse)."""
    memo = getattr(utente, "_ai_consentite", None)
    if memo is None:
        memo = consentite(utente)
        utente._ai_consentite = memo
    return memo


def con_la_chat(utente, azienda):
    """L'utente può lavorare in chat con `azienda`? Se è tra le sue e l'app Chat vale lì (può essere riservata ad alcune
    aziende, Modulo.aziende): solo verso queste si propone il cambio, altrimenti si arriverebbe a una chat che dice 403."""
    return azienda in aziende_di(utente) and modules.per_azienda("ai", azienda, utente)


def da_passare(utente, azienda, oggetto):
    """L'azienda della chat o dell'area se è un'altra in cui l'utente usa la chat: prima di aprirla si passa a quella.
    None se è la corrente, se la chat non ha area o se lì l'utente non usa la chat."""
    altra = altra_azienda(oggetto, azienda)
    return altra if altra is not None and con_la_chat(utente, altra) else None


def senza_chat(utente, azienda, oggetto):
    """La chat o l'area è di un'altra azienda dell'utente in cui l'app Chat non c'è: non si apre e non ci si passa (404).
    Un'azienda che l'utente non ha più resta com'era (le sue chat si leggono, non si scrivono)."""
    altra = altra_azienda(oggetto, azienda)
    return altra is not None and altra in aziende_di(utente) and not con_la_chat(utente, altra)


def rifiuto(utente, azienda, oggetto):
    """Perché Ada non lavora su una chat (o in un'area) di un'altra azienda, per esempio da una scheda rimasta aperta
    dopo un cambio: risponderebbe con i dati dell'azienda corrente. "" se l'azienda è quella corrente."""
    altra = altra_azienda(oggetto, azienda)
    if altra is None:
        return ""
    cosa = "Quest'area" if isinstance(oggetto, ProgettoChat) else "Questa chat"
    if con_la_chat(utente, altra):
        return f"{cosa} è dell'azienda {altra}: passa a {altra} per continuare."
    return f"{cosa} è dell'azienda {altra}, dove non puoi usare la chat: per continuare apri una chat nuova."


def visibile(utente, azienda, pk):
    """L'area se l'utente la vede, altrimenti None."""
    if not str(pk or "").isdigit():
        return None
    return visibili(utente, azienda).filter(pk=pk).first()


def gestita(utente, azienda, pk):
    """L'area se l'utente l'ha creata (e quindi la gestisce), altrimenti None."""
    if azienda is None or not str(pk or "").isdigit():
        return None
    return ProgettoChat.objects.filter(pk=pk, utente=utente, azienda=azienda).first()


def puo_vedere(utente, area):
    return area is not None and (area.utente_id == utente.pk or area.membri.filter(utente=utente).exists())


def chat_visibili(utente, area):
    """Le chat dell'area che l'utente vede: le sue e quelle condivise dagli altri membri."""
    return Conversazione.objects.filter(progetto=area, nascosta=False).filter(Q(utente=utente) | Q(condivisa=True)).select_related("utente")


def candidati(area_o_azienda, proprietario):
    """Gli utenti attivi della stessa azienda con cui si può condividere (non chi l'ha creata): i colleghi, non gli
    utenti esterni (i clienti del portale), come per documenti, grafici e tabelle (condivisione.colleghi)."""
    azienda = getattr(area_o_azienda, "azienda", area_o_azienda)
    return (get_user_model().objects.filter(is_active=True, profilo__aziende=azienda).exclude(profilo__esterno=True)
            .exclude(pk=proprietario.pk).order_by("first_name", "username"))


def imposta_membri(area, utenti):
    """I membri dell'area diventano `utenti`. Chi esce perde l'accesso: le sue chat escono dall'area (restano sue) e le
    sue attività pianificate non lavorano più lì."""
    from .models import Pianificata
    if area.personale:                                    # l'area personale resta privata
        utenti = []
    nuovi = {u.pk for u in utenti if u.pk != area.utente_id}
    attuali = set(area.membri.values_list("utente_id", flat=True))
    usciti = attuali - nuovi
    MembroArea.objects.filter(progetto=area, utente_id__in=usciti).delete()
    MembroArea.objects.bulk_create([MembroArea(progetto=area, utente_id=pk) for pk in nuovi - attuali])
    if usciti:
        riaccogli(Conversazione.objects.filter(progetto=area, utente_id__in=usciti))
        Pianificata.objects.filter(progetto=area, utente_id__in=usciti).update(progetto=None)
    return nuovi - attuali, usciti


def nome(utente):
    return utente.get_full_name() or utente.username
