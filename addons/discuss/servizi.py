"""Canali, iscrizioni, messaggi, reazioni, non letti e ricerca."""
import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import formats, timezone

from core import allegati, lavori
from core.generici import ct_di
from core.models import Allegato

from . import eventi, testo
from .models import Canale, Iscrizione, Messaggio, Reazione

PAGINA = 50
STESSO_GRUPPO_MINUTI = 5


def nome_di(utente):
    return (utente.get_full_name() or utente.username) if utente else "Utente rimosso"


# --- permessi nel canale ---

def puo_vedere(utente, canale):
    if not utente.has_perm("discuss.view_canale"):
        return False
    return canale.tipo == Canale.PUBBLICO or canale.iscrizioni.filter(utente=utente).exists()


def iscrizione(utente, canale):
    return Iscrizione.objects.filter(utente=utente, canale=canale).first()


def _ruolo(utente, canale):
    i = iscrizione(utente, canale)
    return i.ruolo if i else None


def puo_gestire(utente, canale):
    """Nome, descrizione, tipo, ruoli, archiviazione: gli amministratori del canale e i responsabili del modulo."""
    if canale.diretto:
        return False
    return _ruolo(utente, canale) == Iscrizione.AMMINISTRATORE or utente.has_perm("discuss.change_canale")


def puo_moderare(utente, canale):
    """Togliere i messaggi altrui e, nei canali gestiti, fissarli."""
    if canale.diretto:
        return False
    return (_ruolo(utente, canale) in (Iscrizione.AMMINISTRATORE, Iscrizione.MODERATORE)
            or utente.has_perm("discuss.change_canale"))


def puo_scrivere(utente, canale):
    if canale.archiviato or not utente.has_perm("discuss.add_messaggio"):
        return False
    ruolo = _ruolo(utente, canale)
    if ruolo is None:
        return False
    return not canale.gestito or ruolo != Iscrizione.MEMBRO


def puo_fissare(utente, canale):
    if iscrizione(utente, canale) is None:
        return False
    return not canale.gestito or puo_moderare(utente, canale)


# --- iscrizioni ---

def iscrivi(canale, utente, ultimo_letto=None, ruolo=Iscrizione.MEMBRO):
    if ultimo_letto is None:                       # chi entra non trova lo storico come "non letto"
        ultimo_letto = canale.messaggi.order_by("-pk").values_list("pk", flat=True).first() or 0
    return Iscrizione.objects.get_or_create(canale=canale, utente=utente,
                                            defaults={"ultimo_letto": ultimo_letto, "ruolo": ruolo})[0]


def avviso(canale, autore, corpo):
    """Una riga discreta nella conversazione: non conta tra i non letti e non notifica nessuno."""
    m = Messaggio.objects.create(canale=canale, autore=autore, corpo=corpo, tipo=Messaggio.SISTEMA)
    eventi.emetti("nuovo", canale, m=m.pk, autore=autore.pk if autore else None, avviso=True)
    return m


def entra(canale, utente, da=None):
    """Iscrive e lo dice nel canale, una volta sola."""
    if iscrizione(utente, canale):
        return
    iscrivi(canale, utente)
    if not canale.diretto:
        avviso(canale, utente, f"{nome_di(utente)} è entrato nel canale" if da in (None, utente)
               else f"{nome_di(da)} ha aggiunto {nome_di(utente)}")
    eventi.emetti("barra", utente=utente)


def esci(canale, utente, da=None):
    trovata = Iscrizione.objects.filter(canale=canale, utente=utente)
    if not trovata.exists():
        return
    trovata.delete()
    if canale.diretto:
        return
    avviso(canale, da or utente, f"{nome_di(utente)} è uscito dal canale" if da in (None, utente)
           else f"{nome_di(da)} ha tolto {nome_di(utente)}")
    eventi.emetti("barra", utente=utente)
    _garantisci_amministratore(canale)


def _garantisci_amministratore(canale):
    """Un canale non resta senza amministratore: passa al moderatore più anziano, o al primo iscritto."""
    resti = canale.iscrizioni.order_by("entrato", "pk")
    if not resti.exists() or resti.filter(ruolo=Iscrizione.AMMINISTRATORE).exists():
        return
    erede = resti.filter(ruolo=Iscrizione.MODERATORE).first() or resti.first()
    Iscrizione.objects.filter(pk=erede.pk).update(ruolo=Iscrizione.AMMINISTRATORE)


def cambia_ruolo(canale, utente, ruolo):
    Iscrizione.objects.filter(canale=canale, utente=utente).update(ruolo=ruolo)
    _garantisci_amministratore(canale)
    eventi.emetti("barra", utente=utente)


@transaction.atomic
def crea_canale(nome, tipo, creato_da, membri=(), descrizione="", gestito=False, vocale=False):
    canale = Canale.objects.create(nome=nome.strip()[:80], tipo=tipo, creato_da=creato_da, descrizione=descrizione[:250],
                                   gestito=gestito, vocale=vocale)
    for u in {creato_da, *membri}:
        iscrivi(canale, u, 0, ruolo=Iscrizione.AMMINISTRATORE if u == creato_da else Iscrizione.MEMBRO)
        eventi.emetti("barra", utente=u)
    return canale


@transaction.atomic
def diretto(utenti, nome=""):
    """La conversazione diretta tra esattamente queste persone (creata la prima volta)."""
    pk = sorted({u.pk for u in utenti})
    candidati = (Canale.objects.filter(tipo=Canale.DIRETTO).annotate(n=Count("iscrizioni"))
                 .filter(n=len(pk)))
    for c in candidati.filter(iscrizioni__utente_id=pk[0]):
        if sorted(c.iscrizioni.values_list("utente_id", flat=True)) == pk:
            if nome and c.nome != nome:
                Canale.objects.filter(pk=c.pk).update(nome=nome[:80])
                c.nome = nome[:80]
            return c
    canale = Canale.objects.create(tipo=Canale.DIRETTO, creato_da=utenti[0], nome=nome[:80])
    for u in get_user_model().objects.filter(pk__in=pk):
        iscrivi(canale, u, 0)
        eventi.emetti("barra", utente=u)
    return canale


def gruppo_da(canale, autore, nuovi, nome=""):
    """Dal messaggio diretto a un gruppo: una conversazione nuova, così quella a due resta privata."""
    gruppo = diretto([*canale.membri.all(), *nuovi], nome)
    avviso(gruppo, autore, f"{nome_di(autore)} ha creato il gruppo")
    return gruppo


# --- messaggi ---

@transaction.atomic
def invia(canale, autore, corpo, file=(), risposta_a=None, record=(), host=None, esterno="", silenzioso=False):
    """`record`: i record da mostrare come scheda, oltre a quelli citati con un link nel testo.
    `esterno`: il nome di un visitatore del sito. Il suo testo non è fidato: niente menzioni, schede né anteprime."""
    corpo = (corpo or "").strip()[:10000]
    if not corpo and not file and not record:
        raise ValueError("Il messaggio è vuoto.")
    if risposta_a is not None and (risposta_a.canale_id != canale.pk or risposta_a.eliminato):
        risposta_a = None
    messaggio = Messaggio.objects.create(canale=canale, autore=autore, corpo=corpo, risposta_a=risposta_a, autore_esterno=esterno[:80])
    for f in file:
        allegati.salva(messaggio, f, autore)
    Iscrizione.objects.filter(canale=canale, utente=autore).update(ultimo_letto=messaggio.pk)
    from . import notifiche
    if not silenzioso:                             # mentre risponde l'AI gli operatori non vanno disturbati
        notifiche.da_messaggio(messaggio)
    eventi.emetti("nuovo", canale, m=messaggio.pk, autore=autore.pk if autore else None,
                  menzionati=[] if esterno else [u.pk for u in testo.menzionati(corpo)])
    if risposta_a is not None:
        eventi.emetti("agg", canale, m=risposta_a.pk)
    if esterno:
        return messaggio
    from . import schede
    schede.collega(messaggio, [*record, *schede.riconosci(corpo, host)])
    if canale.livechat:
        from .models import ConversazioneEsterna
        # un collega che scrive subentra all'AI
        ConversazioneEsterna.objects.filter(canale=canale, gestita_da=ConversazioneEsterna.AI).update(gestita_da=ConversazioneEsterna.PERSONA)
        from . import assegnazioni
        assegnazioni.chi_scrive_la_prende(canale, autore)
        if ConversazioneEsterna.objects.filter(canale=canale, connessione__isnull=False).exists():
            from . import connettori
            connettori.accoda(messaggio)
        else:
            transaction.on_commit(lambda: lavori.accoda("discuss.livechat.avvisa_visitatore", messaggio=messaggio.pk, ritardo=120))
    if testo.link_di(corpo):
        transaction.on_commit(lambda: lavori.accoda("discuss.anteprime.calcola", messaggio=messaggio.pk))
    if canale.lista_email:
        transaction.on_commit(lambda: lavori.accoda("discuss.posta_canali.invia_lista", messaggio=messaggio.pk))
    return messaggio


def modifica(messaggio, corpo):
    messaggio.corpo, messaggio.modificato_il = corpo.strip()[:10000], timezone.now()
    messaggio.save(update_fields=["corpo", "modificato_il"])
    eventi.emetti("agg", messaggio.canale, m=messaggio.pk)


def elimina(messaggio):
    messaggio.corpo, messaggio.eliminato, messaggio.anteprime = "", True, []
    messaggio.fissato_il = messaggio.fissato_da = None
    messaggio.save(update_fields=["corpo", "eliminato", "anteprime", "fissato_il", "fissato_da"])
    allegati.di(messaggio).delete()
    messaggio.reazioni.all().delete()
    eventi.emetti("agg", messaggio.canale, m=messaggio.pk)


def reagisci(messaggio, utente, emoji):
    """Mette la reazione, o la toglie se c'era già."""
    trovata = Reazione.objects.filter(messaggio=messaggio, utente=utente, emoji=emoji)
    if trovata.exists():
        trovata.delete()
    else:
        Reazione.objects.create(messaggio=messaggio, utente=utente, emoji=emoji)
    eventi.emetti("agg", messaggio.canale, m=messaggio.pk)


def fissa(messaggio, utente):
    """Fissa il messaggio nel canale, o lo toglie."""
    if messaggio.fissato_il:
        messaggio.fissato_il = messaggio.fissato_da = None
    else:
        messaggio.fissato_il, messaggio.fissato_da = timezone.now(), utente
    messaggio.save(update_fields=["fissato_il", "fissato_da"])
    eventi.emetti("agg", messaggio.canale, m=messaggio.pk, n_fissati=len(fissati(messaggio.canale)))


def fissati(canale):
    return list(canale.messaggi.filter(fissato_il__isnull=False, eliminato=False).select_related("autore", "fissato_da")
                .order_by("-fissato_il"))


def segna_letto(utente, canale, fino_a):
    """Avanza fin dove si è letto, a meno che la persona abbia chiesto di tenere la conversazione da leggere."""
    Iscrizione.objects.filter(utente=utente, canale=canale, ultimo_letto__lt=fino_a, tieni_non_letto=False).update(ultimo_letto=fino_a)


def segna_da_leggere(utente, messaggio):
    """Da questo messaggio in poi torna tutto da leggere, fino alla prossima volta che si apre la conversazione."""
    precedente = (messaggio.canale.messaggi.filter(pk__lt=messaggio.pk).order_by("-pk").values_list("pk", flat=True).first() or 0)
    Iscrizione.objects.filter(utente=utente, canale=messaggio.canale).update(ultimo_letto=precedente, tieni_non_letto=True)
    eventi.emetti("barra", utente=utente)


def iscrizioni_di(utente):
    """Le conversazioni dell'utente con il numero di messaggi non letti (degli altri), le più recenti prima."""
    non_letti = (Messaggio.objects.filter(canale=OuterRef("canale"), pk__gt=OuterRef("ultimo_letto"), eliminato=False,
                                          tipo=Messaggio.NORMALE)
                 .exclude(autore=utente).order_by().values("canale").annotate(n=Count("pk")).values("n"))
    recente = Messaggio.objects.filter(canale=OuterRef("canale"), eliminato=False, tipo=Messaggio.NORMALE).order_by("-pk")
    return (Iscrizione.objects.filter(utente=utente, canale__archiviato=False)
            .select_related("canale", "canale__esterna", "canale__esterna__assegnata_a").prefetch_related("canale__membri")
            .annotate(non_letti=Subquery(non_letti), ultimo=Subquery(recente.values("pk")[:1]),
                      ultimo_testo=Subquery(recente.values("corpo")[:1]))
            .order_by(F("ultimo").desc(nulls_last=True), "canale__nome"))


def totale_non_letti(utente):
    return sum(i.non_letti or 0 for i in iscrizioni_di(utente))


def messaggi(canale, dopo=None, prima=None):
    qs = canale.messaggi.select_related("autore", "risposta_a__autore")
    if dopo is not None:
        return list(qs.filter(pk__gt=dopo)[:200])
    if prima is not None:
        qs = qs.filter(pk__lt=prima)
    return list(reversed(qs.order_by("-pk")[:PAGINA]))


def attorno(canale, pk):
    """I messaggi prima e dopo uno preciso: per arrivarci da una ricerca o da un messaggio fissato."""
    qs = canale.messaggi.select_related("autore", "risposta_a__autore")
    meta = PAGINA // 2
    return list(reversed(qs.filter(pk__lte=pk).order_by("-pk")[:meta])) + list(qs.filter(pk__gt=pk)[:meta])


def _etichetta_giorno(giorno):
    oggi = timezone.localdate()
    if giorno == oggi:
        return "Oggi"
    if giorno == oggi - datetime.timedelta(days=1):
        return "Ieri"
    return formats.date_format(giorno, "l j F" if giorno.year == oggi.year else "j F Y")


def _tipo_file(a):
    if a.mime.startswith("image/"):
        return "immagine"
    if a.mime.startswith("audio/") or a.nome.startswith("messaggio-vocale"):
        return "audio"
    return "file"


def prepara(elenco, utente, precedente=None):
    """Tutto ciò che il template mostra di ogni messaggio, con poche query: reazioni, file, risposte, raggruppamento."""
    pk = [m.pk for m in elenco]
    if not pk:
        return elenco
    reazioni, file_di, risposte = {}, {}, {}
    for r in Reazione.objects.filter(messaggio_id__in=pk).select_related("utente"):
        gruppo = reazioni.setdefault(r.messaggio_id, {}).setdefault(r.emoji, {"emoji": r.emoji, "n": 0, "mia": False, "nomi": []})
        gruppo["n"] += 1
        gruppo["mia"] = gruppo["mia"] or r.utente_id == utente.pk
        gruppo["nomi"].append(nome_di(r.utente))
    for a in Allegato.objects.filter(content_type=ct_di(Messaggio), object_id__in=pk):
        a.tipo_file = _tipo_file(a)
        file_di.setdefault(a.object_id, []).append(a)
    for riga in (Messaggio.objects.filter(risposta_a_id__in=pk, eliminato=False).order_by().values("risposta_a_id")
                 .annotate(n=Count("pk"))):
        risposte[riga["risposta_a_id"]] = riga["n"]
    for m in elenco:
        m.gruppi_reazioni = list(reazioni.get(m.pk, {}).values())
        m.file = file_di.get(m.pk, [])
        m.ha_audio = any(a.tipo_file == "audio" for a in m.file)
        m.n_risposte = risposte.get(m.pk, 0)
        giorno = timezone.localtime(m.creato).date()
        nuovo_giorno = precedente is None or timezone.localtime(precedente.creato).date() != giorno
        m.giorno = _etichetta_giorno(giorno) if nuovo_giorno else ""
        m.continua = (precedente is not None and not nuovo_giorno and precedente.autore_id == m.autore_id
                      and precedente.autore_esterno == m.autore_esterno      # visitatore e AI non hanno un utente: sono due persone
                      and precedente.tipo == Messaggio.NORMALE and m.tipo == Messaggio.NORMALE and not m.risposta_a_id
                      and not precedente.eliminato
                      and m.creato - precedente.creato < datetime.timedelta(minutes=STESSO_GRUPPO_MINUTI))
        precedente = m
    return elenco


def uno(pk):
    return Messaggio.objects.select_related("canale", "autore", "risposta_a__autore").filter(pk=pk).first()


def risposte_a(messaggio):
    return list(messaggio.risposte.filter(eliminato=False).select_related("autore", "risposta_a__autore").order_by("pk"))


def file_del_canale(canale, limite=100):
    pk = canale.messaggi.filter(eliminato=False).values("pk")
    return list(Allegato.objects.filter(content_type=ct_di(Messaggio), object_id__in=pk).order_by("-pk")[:limite])


def pubblici_da_scoprire(utente):
    return Canale.objects.filter(tipo=Canale.PUBBLICO, archiviato=False).exclude(iscrizioni__utente=utente)


def visibili(utente):
    """I canali in cui una persona può leggere: quelli in cui è iscritta e i pubblici."""
    return Canale.objects.filter(Q(tipo=Canale.PUBBLICO) | Q(pk__in=Iscrizione.objects.filter(utente=utente).values("canale_id")))


def cerca(utente, q, canale=None, limite=40):
    """Cerca nei messaggi che la persona può leggere. Oltre alle parole: da:nome, in:canale, ha:file, ha:link, fissato:si."""
    parole, qs = [], Messaggio.objects.filter(eliminato=False, tipo=Messaggio.NORMALE, canale__in=visibili(utente))
    if canale is not None:
        qs = qs.filter(canale=canale)
    filtri = False
    for pezzo in (q or "").split():
        chiave, _, valore = pezzo.partition(":")
        chiave, valore = chiave.lower(), valore.strip()
        if chiave == "da" and valore:
            qs = qs.filter(Q(autore__username__icontains=valore) | Q(autore__first_name__icontains=valore)
                           | Q(autore__last_name__icontains=valore))
        elif chiave == "in" and valore:
            qs = qs.filter(canale__nome__icontains=valore.lstrip("#"))
        elif chiave == "ha" and valore == "file":
            qs = qs.filter(pk__in=Allegato.objects.filter(content_type=ct_di(Messaggio)).values("object_id"))
        elif chiave == "ha" and valore == "link":
            qs = qs.filter(Q(corpo__icontains="http://") | Q(corpo__icontains="https://"))
        elif chiave == "fissato":
            qs = qs.filter(fissato_il__isnull=False)
        else:
            parole.append(pezzo)
            continue
        filtri = True
    if not parole and not filtri:
        return []
    for p in parole:
        qs = qs.filter(corpo__icontains=p)
    return list(qs.select_related("canale", "autore").order_by("-pk")[:limite])
