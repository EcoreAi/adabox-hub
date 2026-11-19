"""L'apertura di «Parla con Ada»: quando qualcuno si collega Ada dice per prima una cosa sola, quella che conta di più
in quel momento. La prima volta nella giornata saluta e parte dall'agenda; tornando dopo un po' ricorda l'appuntamento
vicino, la modifica rimasta in sospeso o propone di riprendere la conversazione di prima; tornando dopo pochi minuti
non dice nulla.

La frase la compone il server dai dati, non il modello: è pronta subito, non costa, e orari e numeri non possono essere
inventati. Ogni cosa si dice una volta sola (ai.models.Apertura è il ricordo di ciò che è stato detto). Il modello
entra quando l'utente risponde, e riceve come nota la frase d'apertura e le conversazioni a voce della giornata."""
import datetime
import re

from django.db.models import Count, Q
from django.utils import timezone

from . import riservatezza
from .models import Apertura, Conversazione, MessaggioChat, Proposta, Turno

POCO_FA = datetime.timedelta(minutes=10)         # tornando entro questo tempo Ada non dice nulla
VICINO = datetime.timedelta(minutes=60)          # un appuntamento che comincia entro questo tempo si ricorda
TENUTE = datetime.timedelta(days=2)              # oltre, le aperture si cancellano
TURNI_PER_RIPRENDERE = 2                         # una domanda con la sua risposta non è una conversazione da riprendere
CONVERSAZIONI_IN_NOTA = 3
# senza genere: del nome non si sa se è «bentornato» o «bentornata»
RIVEDERSI = ["piacere di rivederti", "che piacere risentirti", "felice di risentirti"]
RITORNI = ["Rieccoti", "Eccoti di nuovo", "Ciao di nuovo"]
TITOLI = {Apertura.GIORNO: "Inizio giornata", Apertura.APPUNTAMENTO: "Prossimo appuntamento",
          Apertura.SOSPESO: "Modifica in sospeso"}
OFFERTA_AGENDA = "Vuoi sapere cosa hai in agenda per oggi?"

NOTA_APERTURA = ("Hai aperto tu la conversazione dicendo all'utente: «{testo}». Vi siete già salutati: non salutare di "
                 "nuovo. Se accetta quello che hai proposto fallo subito, leggendo i dati con gli strumenti; se chiede "
                 "altro, rispondi a quello.")
NOTA_RIPRESA = ("L'utente è tornato dopo una pausa e gli hai appena detto: «{testo}». Ha scelto di riprendere questa "
                "conversazione: non salutare di nuovo, ricordagli in una frase dove eravate rimasti e chiedi come vuole "
                "proseguire.")
# la conferma di una modifica resta un bottone nella chat (ai.proposte): a voce Ada la ricorda soltanto
NOTA_SOSPESO = (" La modifica si conferma solo con il bottone nella chat: tu non puoi confermarla né eseguirla, e non "
                "dire che è fatta. Se l'utente vuole confermarla, digli di aprire la chat: è nella conversazione «{titolo}».")
NOTA_OGGI = "Oggi a voce avete già parlato di:"
NOTA_OGGI_USO = "Usalo solo se l'utente vi fa riferimento («come dicevamo prima»): non citarlo di tua iniziativa."

_SI = re.compile(r"^\W*(s[iì]|certo|certamente|ok|okay|va bene|d'accordo|volentieri|riprendiamo|riprendi|perché no)\b", re.I)


def _ora():
    return timezone.now()


def nome_di(utente):
    return utente.first_name or utente.get_full_name() or utente.username


def _cita(titolo):
    """Tra virgolette, a meno che il titolo le abbia già («Crea evento «Riunione»»: due volte stonano)."""
    return titolo if "«" in titolo else f"«{titolo}»"


def accetta(testo):
    """La risposta è un sì? Serve solo a scegliere tra riprendere la conversazione di prima e aprirne una nuova."""
    return bool(_SI.match(testo or ""))


# ---------- quando si è visto l'ultima volta ----------

def _mie(utente, azienda):
    return Apertura.objects.filter(utente=utente, azienda=azienda)


def _turni_a_voce(utente, azienda):
    return Turno.objects.filter(utente=utente, azienda=azienda, voce=True, compito="chat")


def _mezzanotte(adesso):
    return timezone.localtime(adesso).replace(hour=0, minute=0, second=0, microsecond=0)


def _ultima_presenza(utente, azienda):
    """L'ultima volta che l'utente ha sentito Ada o le ha parlato a voce."""
    istanti = [_mie(utente, azienda).exclude(detta=None).order_by("-detta").values_list("detta", flat=True).first(),
               _turni_a_voce(utente, azienda).order_by("-iniziato").values_list("iniziato", flat=True).first()]
    return max((i for i in istanti if i), default=None)


def presente_oggi(utente, azienda, adesso=None):
    ultima = _ultima_presenza(utente, azienda)
    return ultima is not None and ultima >= _mezzanotte(adesso or _ora())


def segna_detta(apertura, adesso=None):
    if apertura.detta is None:
        apertura.detta = adesso or _ora()
        apertura.save(update_fields=["detta"])
    return apertura


# ---------- i dati ----------

def _appuntamenti(request, adesso):
    """Gli appuntamenti di oggi non ancora cominciati, come li dà lo strumento dell'agenda: gli stessi che Ada elenca
    se l'utente dice di sì. Vuoto se l'utente non ha il calendario o se l'azienda lo tiene riservato."""
    azienda = getattr(request, "azienda", None)
    if "calendario" in riservatezza.app_riservate(azienda):
        return []
    from . import strumenti
    agenda = next((s for s in strumenti.disponibili(request.user, azienda=azienda) if s.nome == "calendario_agenda"), None)
    if agenda is None:
        return []
    oggi = timezone.localtime(adesso).date().isoformat()
    try:
        eventi = agenda.funzione(strumenti.Contesto(utente=request.user, azienda=azienda), da=oggi, a=oggi)["eventi"]
    except strumenti.ErroreStrumento:
        return []
    locale = timezone.localtime(adesso).replace(tzinfo=None)
    futuri = []
    for e in eventi:
        inizio = datetime.datetime.strptime(e["inizio"], "%Y-%m-%d %H:%M")
        if not e["tutto_il_giorno"] and inizio > locale:
            futuri.append({"id": e["id"], "titolo": e["titolo"], "inizio": inizio, "tra": inizio - locale,
                           "passati_oggi": 0})
    passati = sum(1 for e in eventi if not e["tutto_il_giorno"] and e["inizio"][:10] == oggi) - len(futuri)
    for f in futuri:
        f["passati_oggi"] = passati
    return futuri


def notifiche_non_lette(utente):
    """Le notifiche non lette delle Comunicazioni; None se la persona non le usa."""
    if not utente.has_perm("discuss.view_canale"):
        return None
    try:
        from discuss.notifiche import non_lette
    except ImportError:
        return None
    return non_lette(utente)


# ---------- le frasi ----------

def _saluto(utente, adesso, gia_visto):
    locale = timezone.localtime(adesso)
    parola = "Buongiorno" if locale.hour < 13 else "Buon pomeriggio" if locale.hour < 18 else "Buonasera"
    rivedersi = f", {RIVEDERSI[locale.toordinal() % len(RIVEDERSI)]}" if gia_visto else ""
    return f"{parola} {nome_di(utente)}{rivedersi}."


def _del_giorno(request, adesso, gia_visto):
    utente, azienda = request.user, getattr(request, "azienda", None)
    saluto = _saluto(utente, adesso, gia_visto)
    futuri = _appuntamenti(request, adesso)
    if futuri:
        primo, restano = futuri[0], bool(futuri[0]["passati_oggi"])
        if len(futuri) == 1:
            corpo = (f"Oggi {'ti resta' if restano else 'hai'} un appuntamento alle {primo['inizio']:%H:%M}: "
                     f"{_cita(primo['titolo'])}. Come posso aiutarti?")
        else:
            corpo = (f"Oggi {'ti restano' if restano else 'hai'} {len(futuri)} appuntamenti, "
                     f"il {'prossimo' if restano else 'primo'} alle {primo['inizio']:%H:%M}: {_cita(primo['titolo'])}. {OFFERTA_AGENDA}")
        return {"tipo": Apertura.GIORNO, "testo": f"{saluto} {corpo}", "riferimento": str(primo["id"])}
    notifiche = None if "discuss" in riservatezza.app_riservate(azienda) else notifiche_non_lette(utente)
    if notifiche:
        corpo = ("Hai una notifica non letta: vuoi sentirla?" if notifiche == 1
                 else f"Hai {notifiche} notifiche non lette: vuoi sentirle?")
    else:
        corpo = "Come posso aiutarti?"
    return {"tipo": Apertura.GIORNO, "testo": f"{saluto} {corpo}"}


def _tra(distanza):
    minuti = max(1, round(distanza.total_seconds() / 60))
    return "Tra un minuto" if minuti == 1 else "Tra un'ora" if minuti == 60 else f"Tra {minuti} minuti"


def _appuntamento(request, adesso, dette, ritorno):
    """Il prossimo appuntamento, se comincia entro un'ora e non è già stato ricordato (anche dal saluto del giorno,
    se era già vicino)."""
    for e in _appuntamenti(request, adesso):
        if e["tra"] > VICINO:
            return None
        inizio = timezone.make_aware(e["inizio"], timezone.get_current_timezone())
        ricordato = any(a.riferimento == str(e["id"]) and (a.tipo == Apertura.APPUNTAMENTO
                        or (a.tipo == Apertura.GIORNO and a.detta >= inizio - VICINO)) for a in dette)
        if not ricordato:
            return {"tipo": Apertura.APPUNTAMENTO, "riferimento": str(e["id"]),
                    "testo": f"{ritorno} {_tra(e['tra'])}, alle {e['inizio']:%H:%M}, hai {_cita(e['titolo'])}."}
    return None


def _sospeso(utente, azienda, adesso, dette, ritorno):
    """L'ultima modifica preparata da Ada che aspetta ancora la conferma (si conferma con il bottone, nella chat)."""
    gia = {a.riferimento for a in dette if a.tipo == Apertura.SOSPESO}
    proposta = (Proposta.objects.filter(utente=utente, azienda=azienda, stato=Proposta.IN_ATTESA, creata__gt=adesso - Proposta.DURATA,
                                        conversazione__nascosta=False, conversazione__riservata=False)
                .exclude(pk__in=[int(r) for r in gia if r.isdigit()]).order_by("-pk").first())
    if proposta is None:
        return None
    return {"tipo": Apertura.SOSPESO, "riferimento": str(proposta.pk), "conversazione": proposta.conversazione,
            "testo": f"{ritorno} È rimasta in sospeso una modifica: {_cita(proposta.titolo)}. Aspetta la tua conferma nella chat."}


def _a_voce_di_oggi(utente, azienda, adesso):
    """Le conversazioni a voce di oggi che si possono citare (non quelle riservate), dalla più recente."""
    turni = Q(turni__voce=True, turni__compito="chat", turni__azienda=azienda, turni__iniziato__gte=_mezzanotte(adesso))
    return (Conversazione.objects.filter(utente=utente, nascosta=False, riservata=False)
            .annotate(a_voce=Count("turni", filter=turni, distinct=True)).filter(a_voce__gte=1)
            .order_by("-aggiornata", "-pk"))


def _riprendi(utente, azienda, adesso, dette, ritorno):
    gia = {a.riferimento for a in dette if a.tipo == Apertura.RIPRENDI}
    for c in _a_voce_di_oggi(utente, azienda, adesso).filter(a_voce__gte=TURNI_PER_RIPRENDERE)[:5]:
        if str(c.pk) in gia:
            continue
        testo = (f"{ritorno} Prima parlavamo di {_cita(c.titolo)}: riprendiamo da lì?" if c.titolo_generato
                 else f"{ritorno} Vuoi riprendere la conversazione di prima?")
        return {"tipo": Apertura.RIPRENDI, "riferimento": str(c.pk), "conversazione": c, "testo": testo}
    return None


# ---------- comporre ----------

def componi(request, adesso=None, da_capo=False):
    """L'apertura da mostrare e far dire ora, o None se non c'è niente che valga la pena dire. `da_capo` (per le demo)
    dimentica quelle già dette: Ada saluta come la prima volta nella giornata."""
    utente, azienda = request.user, getattr(request, "azienda", None)
    adesso = adesso or _ora()
    mie = _mie(utente, azienda)
    scadute = mie.filter(Q(detta=None) | Q(creata__lt=adesso - TENUTE))
    (mie if da_capo else scadute).delete()
    ultima = _ultima_presenza(utente, azienda)
    if ultima is not None and adesso - ultima < POCO_FA and not da_capo:
        return None
    dette = list(mie.exclude(detta=None))
    di_oggi = [a for a in dette if a.detta >= _mezzanotte(adesso)]
    if not di_oggi:
        scelta = _del_giorno(request, adesso, gia_visto=ultima is not None)
    else:
        ritorno = f"{RITORNI[(len(di_oggi) - 1) % len(RITORNI)]}, {nome_di(utente)}."
        scelta = (_appuntamento(request, adesso, di_oggi, ritorno) or _sospeso(utente, azienda, adesso, dette, ritorno)
                  or _riprendi(utente, azienda, adesso, dette, ritorno))
    return Apertura.objects.create(utente=utente, azienda=azienda, creata=adesso, **scelta) if scelta else None


# ---------- le note per il modello ----------

def titolo(apertura):
    """Il titolo della conversazione nata da un sì: «Sì» non dice di cosa si parla."""
    if apertura.tipo == Apertura.GIORNO and OFFERTA_AGENDA in apertura.testo:
        return "Agenda di oggi"
    return TITOLI.get(apertura.tipo, "")


def nota(apertura, ripresa=False):
    testo = (NOTA_RIPRESA if ripresa else NOTA_APERTURA).format(testo=apertura.testo)
    if apertura.tipo == Apertura.SOSPESO and apertura.conversazione is not None:
        testo += NOTA_SOSPESO.format(titolo=_corto(apertura.conversazione.titolo, 80))
    return testo


def _corto(testo, massimo):
    testo = " ".join((testo or "").split())
    return testo if len(testo) <= massimo else testo[:massimo].rstrip() + "…"


def nota_oggi(utente, azienda, adesso=None):
    """La memoria della giornata per una conversazione nuova: di che cosa si è già parlato a voce oggi, con l'ultima
    domanda e l'ultima risposta. Le chat riservate non ci entrano: questa nota può andare a un modello cloud."""
    adesso = adesso or _ora()
    righe = []
    for c in _a_voce_di_oggi(utente, azienda, adesso)[:CONVERSAZIONI_IN_NOTA]:
        riga = f"- alle {timezone.localtime(c.aggiornata):%H:%M}, «{_corto(c.titolo, 80)}»"
        ultimi = {m.ruolo: m.testo for m in reversed(list(c.messaggi.order_by("-creato", "-pk")[:6]))}
        if ultimi.get(MessaggioChat.UTENTE):
            riga += f": l'utente ha chiesto «{_corto(ultimi[MessaggioChat.UTENTE], 140)}»"
            if ultimi.get(MessaggioChat.ASSISTENTE):
                riga += f" e hai risposto «{_corto(ultimi[MessaggioChat.ASSISTENTE], 240)}»"
        righe.append(riga)
    return "\n".join([NOTA_OGGI, *righe, NOTA_OGGI_USO]) if righe else ""
