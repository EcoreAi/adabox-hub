"""Progetti della chat collegati a record del gestionale. Il collegamento non dà accesso a nulla: ogni record si legge
con i permessi di chi guarda (Ada compresa, che lavora con i permessi dell'utente). Se l'utente non vede più il record,
il collegamento resta ma non compare."""
import time

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import NoReverseMatch

from .models import CollegamentoProgetto, ProgettoChat

PER_VISTA = 4
TEMPO_MASSIMO = 3.0
MASSIMI = 8                                             # collegamenti per progetto mostrati e passati ad Ada
ESCLUSE = {"ai"}                                        # le cose della chat stessa non si collegano


def cerca(request, testo):
    """[{ct, pk, titolo, vista, app}] dei record che l'utente vede e che contengono `testo` (come «Cerca ovunque»)."""
    from core.viste import filtri
    from core.viste.interroga import viste_accessibili

    from .conoscenza import MODELLI_ESCLUSI              # registro modifiche, coda dei lavori, email grezze...
    risultati, inizio = [], time.monotonic()
    for vista in viste_accessibili(request):
        if (vista.modulo in ESCLUSE or vista.opts.label_lower in MODELLI_ESCLUSI or not vista.search_fields
                or time.monotonic() - inizio > TEMPO_MASSIMO):
            continue
        qs = filtri.applica(vista, request, vista.get_queryset(request), parametri={"q": testo})
        ct = ContentType.objects.get_for_model(vista.model)
        risultati += [{"ct": ct.pk, "pk": o.pk, "titolo": str(o)[:120], "vista": str(vista.verbose_name).capitalize(), "app": vista.modulo}
                      for o in qs[:PER_VISTA]]
    return risultati[:30]


def risolvi(request, ct_id, pk):
    """(vista, record) se l'utente lo vede, altrimenti None."""
    from core.generici import vista_e_oggetto
    try:
        return vista_e_oggetto(request, ct_id, pk)
    except (Http404, PermissionDenied, ValueError, LookupError):
        return None


def del_progetto(request, progetto):
    """[{collegamento, vista, obj, titolo, tipo, url, id_vista}] che l'utente vede."""
    from core.viste.interroga import id_vista
    voci = []
    for c in progetto.collegamenti.select_related("content_type")[:MASSIMI * 2]:
        trovato = risolvi(request, c.content_type_id, c.object_id)
        if trovato is None:
            continue
        vista, obj = trovato
        try:
            url = vista.url("dettaglio", pk=obj.pk)
        except NoReverseMatch:
            url = ""
        voci.append({"collegamento": c, "vista": vista, "obj": obj, "titolo": str(obj)[:120], "tipo": str(vista.verbose_name).capitalize(),
                     "url": url, "id_vista": id_vista(vista)})
    return voci[:MASSIMI]


def nota(utente, progetto):
    """Per Ada: i record collegati, da leggere con leggi_record quando servono."""
    from .strumenti import Contesto, richiesta
    if not progetto.collegamenti.exists():
        return ""
    request = richiesta.per(Contesto(utente=utente, azienda=progetto.azienda))
    voci = del_progetto(request, progetto)
    if not voci:
        return ""
    elenco = "; ".join(f"{v['tipo']} «{v['titolo']}» (vista {v['id_vista']}, id {v['obj'].pk})" for v in voci)
    return (f"L'area di lavoro è collegata a questi record del gestionale: {elenco}. Quando la domanda li riguarda (stato, scadenze, "
            "attività, persone), leggili con leggi_record invece di chiedere all'utente di cosa si parla.")


def progetti_del_record(utente, azienda, obj):
    """Le aree di lavoro che l'utente vede (sue o condivise con lui) collegate a questo record."""
    from . import aree
    if azienda is None:
        return []
    ct = ContentType.objects.get_for_model(type(obj))
    return list(aree.visibili(utente, azienda).filter(collegamenti__content_type=ct, collegamenti__object_id=obj.pk).distinct())


def contenuto(utente, area, quanti=5):
    """Che cosa è nato nell'area, per la sezione nel record collegato: le chat che l'utente vede, i documenti scritti con
    Ada e i grafici e le tabelle di quelle chat (mai le chat private degli altri membri)."""
    from . import aree
    from .models import Artifact, DocumentoChat
    chat = aree.chat_visibili(utente, area)
    return {"chat": list(chat.order_by("-aggiornata")[:quanti]),
            "documenti": list(DocumentoChat.objects.filter(conversazione__in=chat).order_by("-aggiornato")[:quanti]),
            "grafici": list(Artifact.objects.filter(conversazione__in=chat).order_by("-pk")[:quanti]),
            "n_membri": area.membri.count()}


def persone_del_record(obj):
    """Gli utenti citati dal record (responsabile, membri…): i colleghi da proporre per un'area nata da lì."""
    from django.contrib.auth import get_user_model
    Utente = get_user_model()
    trovati = []
    for f in obj._meta.get_fields():
        if getattr(f, "related_model", None) is not Utente or f.auto_created:
            continue
        if f.many_to_many:
            trovati += list(getattr(obj, f.name).filter(is_active=True))
        elif f.many_to_one and getattr(obj, f.name, None) is not None and getattr(obj, f.name).is_active:
            trovati.append(getattr(obj, f.name))
    return list(dict.fromkeys(trovati))
